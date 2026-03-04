/**
 * Starbridge — Security Station (v0.07)
 *
 * Full interior combat UI with marine team commands, boarding party intel,
 * door control, lockdowns, bulkheads, alert levels, armoury, quarantine.
 *
 * Server messages received:
 *   game.started              — show UI, store static interior_layout
 *   security.interior_state   — full state: teams, parties, rooms, systems
 *   ship.alert_changed        — update station alert colour
 *   ship.hull_hit             — hit-flash border
 *   game.over                 — defeat/victory overlay
 *
 * Server messages sent:
 *   lobby.claim_role          { role: 'security', player_name }
 *   security.send_team        { team_id, destination }
 *   security.set_patrol       { team_id, route: [room_ids] }
 *   security.station_team     { team_id }
 *   security.disengage_team   { team_id }
 *   security.assign_escort    { team_id, repair_team_id }
 *   security.lock_door        { room_id }
 *   security.unlock_door      { room_id }
 *   security.lockdown_deck    { deck }
 *   security.lockdown_all     {}
 *   security.lift_lockdown    { deck }  or { all: true }
 *   security.seal_bulkhead    { deck_above, deck_below }
 *   security.unseal_bulkhead  { deck_above, deck_below }
 *   security.set_deck_alert   { deck, level }
 *   security.arm_crew         { deck }
 *   security.disarm_crew      { deck }
 *   security.quarantine_room  { room_id }
 *   security.lift_quarantine  { room_id }
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import {
  setStatusDot, setAlertLevel, showBriefing, showGameOver,
} from '../shared/ui_components.js';
import { SoundBank } from '../shared/audio.js';
import '../shared/audio_events.js';
import { wireButtonSounds } from '../shared/audio_ui.js';
import { createRenderScheduler, guardInteraction } from '../shared/render_scheduler.js';
import { registerHelp, initHelpOverlay } from '../shared/help_overlay.js';
import { initRoleBar } from '../shared/role_bar.js';
import { initCrewRoster } from '../shared/crew_roster.js';

registerHelp([
  { selector: '#ship-canvas',  text: 'Ship interior — rooms, marine teams (blue ▲), boarders (red ✕). Click rooms to interact.', position: 'right' },
  { selector: '#team-list',    text: 'Marine squads — click to select, use buttons to command.', position: 'left' },
  { selector: '#boarding-list', text: 'Boarding party intelligence and status.', position: 'left' },
  { selector: '.controls-bar', text: 'Security controls: door locks, lockdowns, bulkheads, arm crew, quarantine.', position: 'above' },
]);

// ---------------------------------------------------------------------------
// Canvas constants
// ---------------------------------------------------------------------------

const ROOM_W    = 120;
const ROOM_H    = 70;
const MARGIN    = 40;
const GAP       = 8;

const HIT_FLASH_MS = 500;

const C_BG       = '#0a0a0a';
const C_PRIMARY  = '#00ff41';
const C_FRIENDLY = '#00aaff';
const C_HOSTILE  = '#ff3333';
const C_NEUTRAL  = '#888888';
const C_WARN     = '#ffb000';
const C_FIRE     = '#ff6600';
const C_CONN     = 'rgba(0,255,65,0.18)';

// Dynamic hull geometry — recomputed per layout
let _shipClass = '';
let _hullImg = null;
let _canvasW = MARGIN * 2 + 4 * (ROOM_W + GAP) - GAP;
let _canvasH = MARGIN * 2 + 5 * (ROOM_H + GAP) - GAP;
let _gridCols = 4;
let _gridRows = 5;
let _deckCount = 5;
let _deckBoundariesY = [];
let _deckLabels = {};

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const statusDotEl    = document.querySelector('[data-status-dot]');
const statusLabelEl  = document.querySelector('[data-status-label]');
const standbyEl      = document.querySelector('[data-standby]');
const secMainEl      = document.querySelector('[data-security-main]');
const missionLabelEl = document.getElementById('mission-label');
const stationEl      = document.querySelector('.station-container');

const canvas           = document.getElementById('ship-canvas');
const ctx              = canvas.getContext('2d');
const boardingStatusEl = document.getElementById('boarding-status');
const teamListEl       = document.getElementById('team-list');
const boardingListEl   = document.getElementById('boarding-list');
const alertListEl      = document.getElementById('alert-list');
const escortListEl     = document.getElementById('escort-list');

// ---------------------------------------------------------------------------
// Render throttle + interaction guard
// ---------------------------------------------------------------------------

const guardedRenderTeams  = guardInteraction(() => renderTeams(), teamListEl);
const guardedRenderAlerts = guardInteraction(() => renderAlerts(), alertListEl);

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let layout = {};       // room_id -> { name, deck, col, row, connections[] }
let roomsState = {};   // room_id -> { state, door_sealed }

// Legacy squads + intruders (still rendered if present)
let squads = [];
let intruders = [];
let isBoarding = false;

// Enhanced state (v0.06.3)
let marineTeams = [];      // from interior_state.marine_teams
let boardingParties = [];  // from interior_state.boarding_parties
let lockedDoors = [];
let breachedDoors = [];
let sealedBulkheads = [];
let deckAlerts = {};       // { "1": "normal", ... }
let armedDecks = [];
let quarantinedRooms = [];
let sensorStatus = {};

let selectedTeamId = null;
let selectedRoomId = null;
let selectedSquadId = null;  // legacy

// Hash guards — skip DOM rebuild when data hasn't changed.
let _lastTeamsJson = '';
let _lastAlertsJson = '';
let _lastBoardingJson = '';
let _lastStatusJson = '';

// ---------------------------------------------------------------------------
// Dynamic geometry computation
// ---------------------------------------------------------------------------

function _computeGeometry(layoutData) {
  let maxCol = 0, maxRow = 0, maxDeck = 0;
  const deckRows = {};  // deck_number -> Set of row indices

  for (const r of Object.values(layoutData)) {
    if (r.col > maxCol) maxCol = r.col;
    if (r.row > maxRow) maxRow = r.row;
    const dn = r.deck_number || r.deck_number || parseInt(r.deck) || 1;
    if (dn > maxDeck) maxDeck = dn;
    if (!deckRows[dn]) deckRows[dn] = new Set();
    deckRows[dn].add(r.row);
  }

  _gridCols = maxCol + 1;
  _gridRows = maxRow + 1;
  _deckCount = maxDeck;

  _canvasW = MARGIN * 2 + _gridCols * (ROOM_W + GAP) - GAP;
  _canvasH = MARGIN * 2 + _gridRows * (ROOM_H + GAP) - GAP;

  canvas.width = _canvasW;
  canvas.height = _canvasH;

  // Compute deck boundary Y positions
  _deckBoundariesY = [];
  for (let d = 1; d < _deckCount; d++) {
    const rowsAbove = deckRows[d] || new Set();
    const rowsBelow = deckRows[d + 1] || new Set();
    const lastAbove = Math.max(...rowsAbove);
    const firstBelow = Math.min(...rowsBelow);
    const yAbove = MARGIN + lastAbove * (ROOM_H + GAP) + ROOM_H;
    const yBelow = MARGIN + firstBelow * (ROOM_H + GAP);
    _deckBoundariesY.push((yAbove + yBelow) / 2);
  }

  // Derive deck labels from room names
  _deckLabels = {};
  const deckNameCounts = {};
  for (const r of Object.values(layoutData)) {
    const dn = r.deck_number || r.deck_number || parseInt(r.deck) || 1;
    if (!deckNameCounts[dn]) deckNameCounts[dn] = {};
    const dname = r.crew_deck || r.deck || `Deck ${dn}`;
    deckNameCounts[dn][dname] = (deckNameCounts[dn][dname] || 0) + 1;
  }
  for (const [dn, counts] of Object.entries(deckNameCounts)) {
    let best = '', bestN = 0;
    for (const [name, n] of Object.entries(counts)) {
      if (n > bestN) { best = name; bestN = n; }
    }
    _deckLabels[dn] = best.charAt(0).toUpperCase() + best.slice(1);
  }
}

function _populateDeckControls() {
  // Deck tabs
  const tabContainer = document.getElementById('deck-tabs');
  if (tabContainer) {
    const allBtn = tabContainer.querySelector('[data-deck="0"]');
    tabContainer.innerHTML = '';
    if (allBtn) tabContainer.appendChild(allBtn);
    for (let d = 1; d <= _deckCount; d++) {
      const btn = document.createElement('button');
      btn.className = 'deck-tab';
      btn.dataset.deck = String(d);
      btn.textContent = `D${d}`;
      tabContainer.appendChild(btn);
    }
  }

  // Bulkhead select
  const bSel = document.getElementById('sel-bulkhead');
  if (bSel) {
    bSel.innerHTML = '<option value="">BULKHEAD ▼</option>';
    for (let d = 1; d < _deckCount; d++) {
      bSel.innerHTML += `<option value="seal_${d}_${d + 1}">SEAL D${d}-D${d + 1}</option>`;
    }
    for (let d = 1; d < _deckCount; d++) {
      bSel.innerHTML += `<option value="unseal_${d}_${d + 1}">UNSEAL D${d}-D${d + 1}</option>`;
    }
  }

  // Arm crew select
  const aSel = document.getElementById('sel-arm');
  if (aSel) {
    aSel.innerHTML = '<option value="">ARM CREW ▼</option>';
    for (let d = 1; d <= _deckCount; d++) {
      aSel.innerHTML += `<option value="arm_${d}">ARM DECK ${d}</option>`;
    }
    for (let d = 1; d <= _deckCount; d++) {
      aSel.innerHTML += `<option value="disarm_${d}">DISARM DECK ${d}</option>`;
    }
  }
}

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

function roomPixel(col, row) {
  return { x: MARGIN + col * (ROOM_W + GAP), y: MARGIN + row * (ROOM_H + GAP) };
}

function roomCenter(col, row) {
  const { x, y } = roomPixel(col, row);
  return { x: x + ROOM_W / 2, y: y + ROOM_H / 2 };
}

function roomAtPoint(px, py) {
  for (const [roomId, r] of Object.entries(layout)) {
    const { x, y } = roomPixel(r.col, r.row);
    if (px >= x && px <= x + ROOM_W && py >= y && py <= y + ROOM_H) return roomId;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Hull rendering
// ---------------------------------------------------------------------------

function drawHull() {
  ctx.save();
  if (_hullImg && _hullImg.complete && _hullImg.naturalWidth > 0) {
    // Draw SVG silhouette scaled to canvas as faint background
    ctx.globalAlpha = 0.12;
    ctx.drawImage(_hullImg, 0, 0, _canvasW, _canvasH);
    ctx.globalAlpha = 1.0;
    // Faint border glow
    ctx.shadowBlur = 22; ctx.shadowColor = 'rgba(0,255,65,0.5)';
    ctx.strokeStyle = 'rgba(0,255,65,0.6)'; ctx.lineWidth = 1.5;
    const r = 12;
    ctx.beginPath();
    ctx.moveTo(r, 0); ctx.lineTo(_canvasW - r, 0); ctx.quadraticCurveTo(_canvasW, 0, _canvasW, r);
    ctx.lineTo(_canvasW, _canvasH - r); ctx.quadraticCurveTo(_canvasW, _canvasH, _canvasW - r, _canvasH);
    ctx.lineTo(r, _canvasH); ctx.quadraticCurveTo(0, _canvasH, 0, _canvasH - r);
    ctx.lineTo(0, r); ctx.quadraticCurveTo(0, 0, r, 0);
    ctx.closePath(); ctx.stroke();
    ctx.shadowBlur = 0;
  } else {
    // Fallback: rounded-rect outline
    ctx.fillStyle = '#030d05';
    const r = 12;
    ctx.beginPath();
    ctx.moveTo(r, 0); ctx.lineTo(_canvasW - r, 0); ctx.quadraticCurveTo(_canvasW, 0, _canvasW, r);
    ctx.lineTo(_canvasW, _canvasH - r); ctx.quadraticCurveTo(_canvasW, _canvasH, _canvasW - r, _canvasH);
    ctx.lineTo(r, _canvasH); ctx.quadraticCurveTo(0, _canvasH, 0, _canvasH - r);
    ctx.lineTo(0, r); ctx.quadraticCurveTo(0, 0, r, 0);
    ctx.closePath(); ctx.fill();
    ctx.shadowBlur = 22; ctx.shadowColor = 'rgba(0,255,65,0.5)';
    ctx.strokeStyle = 'rgba(0,255,65,0.6)'; ctx.lineWidth = 1.5; ctx.stroke();
    ctx.shadowBlur = 0;
  }
  ctx.restore();
}

function drawStructure() {
  const cx = _canvasW / 2;
  ctx.save();
  ctx.setLineDash([5, 7]); ctx.strokeStyle = 'rgba(0,255,65,0.18)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(cx, 10); ctx.lineTo(cx, _canvasH - 10); ctx.stroke();
  for (const y of _deckBoundariesY) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(_canvasW, y); ctx.stroke(); }
  ctx.setLineDash([]);
  ctx.font = '10px "Share Tech Mono", monospace'; ctx.fillStyle = 'rgba(0,255,65,0.28)';
  ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.fillText('BOW', cx, 10);
  ctx.textBaseline = 'bottom'; ctx.fillText('STERN', cx, _canvasH - 6);
  const eng = ctx.createRadialGradient(cx, _canvasH - 4, 0, cx, _canvasH - 4, 90);
  eng.addColorStop(0, 'rgba(255,110,0,0.10)'); eng.addColorStop(1, 'rgba(255,110,0,0)');
  ctx.fillStyle = eng; ctx.fillRect(cx - 90, _canvasH - 86, 180, 88);
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Canvas rendering
// ---------------------------------------------------------------------------

function roomStrokeColor(roomId, rs) {
  if (quarantinedRooms.includes(roomId)) return '#ff00ff';
  if (breachedDoors.includes(roomId)) return C_NEUTRAL;
  switch (rs.state) {
    case 'damaged':      return C_WARN;
    case 'decompressed': return C_NEUTRAL;
    case 'fire':         return C_FIRE;
    default:             return C_PRIMARY;
  }
}

function doorLineStyle(roomId) {
  if (breachedDoors.includes(roomId)) return { dash: [2, 3], color: C_NEUTRAL };
  if (lockedDoors.includes(roomId)) return { dash: [3, 4], color: 'rgba(255,51,51,0.5)' };
  return { dash: [], color: C_CONN };
}

function draw() {
  ctx.clearRect(0, 0, _canvasW, _canvasH);
  ctx.fillStyle = C_BG; ctx.fillRect(0, 0, _canvasW, _canvasH);
  drawHull(); drawStructure();
  if (Object.keys(layout).length === 0) return;

  // 1. Connection lines
  const drawnConns = new Set();
  for (const [roomId, r] of Object.entries(layout)) {
    for (const connId of r.connections) {
      const key = [roomId, connId].sort().join(':');
      if (drawnConns.has(key)) continue;
      drawnConns.add(key);
      const conn = layout[connId]; if (!conn) continue;
      const a = roomCenter(r.col, r.row);
      const b = roomCenter(conn.col, conn.row);
      const style = doorLineStyle(connId);
      ctx.save(); ctx.lineWidth = 1; ctx.setLineDash(style.dash);
      ctx.strokeStyle = style.color;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      ctx.restore();
    }
  }

  // 2. Rooms
  for (const [roomId, r] of Object.entries(layout)) {
    const { x, y } = roomPixel(r.col, r.row);
    const rs = roomsState[roomId] || { state: 'normal', door_sealed: false };
    const color = roomStrokeColor(roomId, rs);
    const isSelected = roomId === selectedRoomId;

    // Has hostiles?
    const hasHostiles = boardingParties.some(bp => bp.location === roomId);

    // Fill
    if (hasHostiles) ctx.fillStyle = 'rgba(255,51,51,0.08)';
    else if (isSelected) ctx.fillStyle = 'rgba(0,170,255,0.08)';
    else ctx.fillStyle = 'rgba(0,255,65,0.02)';
    ctx.fillRect(x, y, ROOM_W, ROOM_H);

    // Border
    ctx.strokeStyle = isSelected ? C_FRIENDLY : color;
    ctx.lineWidth = isSelected ? 2 : 1;
    ctx.strokeRect(x, y, ROOM_W, ROOM_H);

    // Sealed indicator
    if (rs.door_sealed) {
      const dc = breachedDoors.includes(roomId) ? C_NEUTRAL
               : lockedDoors.includes(roomId) ? C_HOSTILE : C_WARN;
      ctx.fillStyle = dc;
      ctx.fillRect(x + ROOM_W - 7, y + 1, 6, 6);
    }

    // Quarantine indicator
    if (quarantinedRooms.includes(roomId)) {
      ctx.fillStyle = 'rgba(255,0,255,0.15)';
      ctx.fillRect(x, y, ROOM_W, ROOM_H);
      ctx.fillStyle = '#ff00ff'; ctx.font = '11px "Share Tech Mono", monospace';
      ctx.textAlign = 'right'; ctx.textBaseline = 'top';
      ctx.fillText('Q', x + ROOM_W - 3, y + 2);
    }

    // Sensor damage overlay
    const sensor = sensorStatus[roomId];
    if (sensor === 'damaged') {
      ctx.fillStyle = 'rgba(0,0,0,0.4)';
      ctx.fillRect(x, y, ROOM_W, ROOM_H);
    }

    // Room name
    ctx.fillStyle = isSelected ? C_FRIENDLY : color;
    ctx.font = '11px "Share Tech Mono", monospace';
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    const label = r.name.length > 15 ? r.name.slice(0, 14) + '\u2026' : r.name;
    ctx.fillText(label, x + ROOM_W / 2, y + 5);
    ctx.fillStyle = 'rgba(0,255,65,0.35)'; ctx.font = '10px "Share Tech Mono", monospace';
    ctx.fillText(r.deck.toUpperCase(), x + ROOM_W / 2, y + 17);
  }

  // 3. Legacy squad tokens (blue circles)
  for (const sq of squads) {
    const r = layout[sq.room_id]; if (!r) continue;
    const center = roomCenter(r.col, r.row);
    ctx.save(); ctx.beginPath(); ctx.arc(center.x, center.y + 10, 13, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(0,170,255,0.12)'; ctx.fill();
    ctx.strokeStyle = C_FRIENDLY; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = C_FRIENDLY; ctx.font = 'bold 11px "Share Tech Mono", monospace';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(String(sq.count), center.x, center.y + 10);
    ctx.restore();
  }

  // 4. Marine team tokens (blue triangles)
  for (const team of marineTeams) {
    const r = layout[team.location]; if (!r) continue;
    const teamsInRoom = marineTeams.filter(t => t.location === team.location);
    const idx = teamsInRoom.indexOf(team);
    const spread = teamsInRoom.length > 1 ? 20 : 0;
    const offset = (idx - (teamsInRoom.length - 1) / 2) * spread;
    const center = roomCenter(r.col, r.row);
    const cx = center.x + offset, cy = center.y + 12;
    const isSel = team.id === selectedTeamId;

    ctx.save();
    // Triangle
    ctx.beginPath(); ctx.moveTo(cx, cy - 8); ctx.lineTo(cx - 7, cy + 5); ctx.lineTo(cx + 7, cy + 5); ctx.closePath();
    ctx.fillStyle = isSel ? 'rgba(0,170,255,0.35)' : 'rgba(0,170,255,0.12)'; ctx.fill();
    ctx.strokeStyle = isSel ? '#66ccff' : C_FRIENDLY; ctx.lineWidth = isSel ? 2 : 1; ctx.stroke();
    // Label
    ctx.fillStyle = C_FRIENDLY; ctx.font = 'bold 11px "Share Tech Mono", monospace';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(String(team.size), cx, cy);
    ctx.restore();
  }

  // 5. Boarding party tokens (red X marks)
  for (const bp of boardingParties) {
    const r = layout[bp.location]; if (!r) continue;
    const center = roomCenter(r.col, r.row);
    const cx = center.x, cy = center.y - 14;
    ctx.save();
    ctx.strokeStyle = C_HOSTILE; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(cx - 6, cy - 6); ctx.lineTo(cx + 6, cy + 6);
    ctx.moveTo(cx + 6, cy - 6); ctx.lineTo(cx - 6, cy + 6); ctx.stroke();
    ctx.fillStyle = C_HOSTILE; ctx.font = 'bold 11px "Share Tech Mono", monospace';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(String(bp.members), cx, cy + 12);
    ctx.restore();
  }

  // 6. Legacy intruder tokens
  for (const intr of intruders) {
    const r = layout[intr.room_id]; if (!r) continue;
    const center = roomCenter(r.col, r.row);
    ctx.save(); ctx.beginPath(); ctx.arc(center.x, center.y - 14, 9, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255,51,51,0.25)'; ctx.fill();
    ctx.strokeStyle = C_HOSTILE; ctx.stroke();
    ctx.fillStyle = C_HOSTILE; ctx.font = 'bold 10px "Share Tech Mono", monospace';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('!', center.x, center.y - 14);
    ctx.restore();
  }
}

// ---------------------------------------------------------------------------
// Sidebar rendering
// ---------------------------------------------------------------------------

function renderAlerts(force = false) {
  const alertsKey = JSON.stringify(deckAlerts);
  if (!force && alertsKey === _lastAlertsJson) return;
  _lastAlertsJson = alertsKey;

  alertListEl.innerHTML = '';
  for (let d = 1; d <= _deckCount; d++) {
    const level = deckAlerts[String(d)] || 'normal';
    const row = document.createElement('div');
    row.className = 'alert-row';
    const deckLabel = _deckLabels[d] || '';
    row.innerHTML = `
      <span class="text-label text-dim">DECK ${d}${deckLabel ? ' ' + deckLabel : ''}</span>
      <span class="alert-badge alert-badge--${level}">${level.toUpperCase()}</span>
    `;
    row.addEventListener('click', () => {
      const levels = ['normal', 'caution', 'combat', 'evacuate'];
      const next = levels[(levels.indexOf(level) + 1) % levels.length];
      send('security.set_deck_alert', { deck: d, level: next });
    });
    alertListEl.appendChild(row);
  }
}

function renderTeams(force = false) {
  const teamsKey = JSON.stringify({ marineTeams, squads, selectedTeamId, selectedSquadId });
  if (!force && teamsKey === _lastTeamsJson) return;
  _lastTeamsJson = teamsKey;

  teamListEl.innerHTML = '';
  if (marineTeams.length === 0) {
    // Fall back to legacy squads
    for (const sq of squads) {
      const isSel = sq.id === selectedSquadId;
      const card = document.createElement('div');
      card.className = `team-card${isSel ? ' team-card--selected' : ''}${sq.count <= 0 ? ' team-card--incap' : ''}`;
      const roomName = layout[sq.room_id]?.name || sq.room_id;
      card.innerHTML = `
        <div class="team-card__header">
          <span class="text-label c-friendly">${sq.id.toUpperCase()}</span>
          <span class="text-data c-friendly">${sq.count} MBR</span>
        </div>
        <div class="team-card__location text-label text-dim">${roomName.toUpperCase()}</div>
      `;
      if (sq.count > 0) card.addEventListener('click', () => { selectedSquadId = isSel ? null : sq.id; draw(); renderTeams(true); });
      teamListEl.appendChild(card);
    }
    return;
  }

  for (const team of marineTeams) {
    const isSel = team.id === selectedTeamId;
    const isIncap = team.status === 'incapacitated';
    const roomName = layout[team.location]?.name || team.location;
    const memberPct = Math.round((team.size / team.max_size) * 100);
    const ammoPct = Math.round(team.ammo);

    const card = document.createElement('div');
    card.className = `team-card${isSel ? ' team-card--selected' : ''}${isIncap ? ' team-card--incap' : ''}`;
    card.innerHTML = `
      <div class="team-card__header">
        <span class="text-label c-friendly">${team.callsign}</span>
        <span class="text-data" style="color:${team.status === 'engaging' ? C_HOSTILE : C_FRIENDLY}">${team.status.toUpperCase()}</span>
      </div>
      <div class="team-card__location text-label text-dim">${roomName.toUpperCase()}</div>
      <div class="team-bar-row">
        <span class="text-label">MBR</span>
        <div class="team-bar gauge"><div class="gauge__fill${memberPct < 50 ? ' gauge__fill--danger' : ''}" style="width:${memberPct}%"></div></div>
        <span class="text-data">${team.size}/${team.max_size}</span>
      </div>
      <div class="team-bar-row">
        <span class="text-label">AMO</span>
        <div class="team-bar gauge"><div class="gauge__fill${ammoPct < 30 ? ' gauge__fill--warn' : ''}" style="width:${ammoPct}%"></div></div>
        <span class="text-data">${ammoPct}%</span>
      </div>
      ${team.engagement ? `<div class="text-label c-hostile" style="font-size:0.75rem">ENGAGING: ${team.engagement}</div>` : ''}
    `;

    // Action buttons
    if (!isIncap) {
      const actions = document.createElement('div');
      actions.className = 'team-actions';

      if (team.status === 'engaging') {
        const btnDis = document.createElement('button');
        btnDis.className = 'team-btn'; btnDis.textContent = 'DISENGAGE';
        btnDis.addEventListener('click', (e) => { e.stopPropagation(); send('security.disengage_team', { team_id: team.id }); });
        actions.appendChild(btnDis);
      } else {
        const btnResp = document.createElement('button');
        btnResp.className = 'team-btn'; btnResp.textContent = 'RESPOND';
        btnResp.addEventListener('click', (e) => {
          e.stopPropagation();
          selectedTeamId = team.id;
          draw(); renderTeams(true);
        });
        actions.appendChild(btnResp);

        const btnSta = document.createElement('button');
        btnSta.className = 'team-btn'; btnSta.textContent = 'STATION';
        btnSta.addEventListener('click', (e) => { e.stopPropagation(); send('security.station_team', { team_id: team.id }); });
        actions.appendChild(btnSta);
      }
      card.appendChild(actions);
    }

    if (!isIncap) {
      card.addEventListener('click', () => { selectedTeamId = isSel ? null : team.id; draw(); renderTeams(true); });
    }
    teamListEl.appendChild(card);
  }
}

function renderBoardingIntel(force = false) {
  const boardingKey = JSON.stringify({ boardingParties, intruders });
  if (!force && boardingKey === _lastBoardingJson) return;
  _lastBoardingJson = boardingKey;

  boardingListEl.innerHTML = '';
  const parties = boardingParties.length > 0 ? boardingParties : [];
  if (parties.length === 0 && intruders.length === 0) {
    boardingListEl.innerHTML = '<p class="text-dim text-label">NO CONTACTS</p>';
    return;
  }

  for (const bp of parties) {
    const roomName = layout[bp.location]?.name || bp.location;
    const moralePct = Math.round((bp.morale || 1) * 100);
    const sabPct = Math.round((bp.sabotage_progress || 0) * 100);
    const card = document.createElement('div');
    card.className = 'bp-card';
    card.innerHTML = `
      <div class="bp-card__row">
        <span class="text-label c-hostile">${bp.id.toUpperCase()}</span>
        <span class="text-data c-hostile">${bp.members}/${bp.max_members}</span>
      </div>
      <div class="bp-detail"><span class="text-label text-dim">LOC:</span><span class="text-label">${roomName.toUpperCase()}</span></div>
      <div class="bp-detail"><span class="text-label text-dim">OBJ:</span><span class="text-label">${(bp.objective || '?').toUpperCase()}</span></div>
      <div class="bp-detail"><span class="text-label text-dim">STS:</span><span class="text-label">${bp.status.toUpperCase()}</span></div>
      ${bp.status === 'sabotaging' ? `<div class="bp-detail"><span class="text-label text-dim">SAB:</span><span class="text-label c-hostile">${sabPct}%</span></div>` : ''}
      <div class="team-bar-row">
        <span class="text-label text-dim">MOR</span>
        <div class="team-bar gauge"><div class="gauge__fill${moralePct < 30 ? ' gauge__fill--danger' : ' gauge__fill--warn'}" style="width:${moralePct}%"></div></div>
      </div>
    `;
    boardingListEl.appendChild(card);
  }

  // Legacy intruders
  for (const intr of intruders) {
    const roomName = layout[intr.room_id]?.name || intr.room_id;
    const item = document.createElement('div');
    item.className = 'bp-card';
    item.innerHTML = `
      <div class="bp-card__row">
        <span class="text-label c-hostile">${intr.id.toUpperCase()}</span>
        <span class="text-data c-hostile">${Math.round(intr.health)}%</span>
      </div>
      <div class="bp-detail"><span class="text-label text-dim">LOC:</span><span class="text-label">${roomName.toUpperCase()}</span></div>
    `;
    boardingListEl.appendChild(item);
  }
}

function renderStatusBar(force = false) {
  const statusKey = JSON.stringify({
    bp: boardingParties.length, mt: marineTeams.map(t => t.status),
    ld: lockedDoors.length, ad: armedDecks, ss: sensorStatus, ib: isBoarding,
  });
  if (!force && statusKey === _lastStatusJson) return;
  _lastStatusJson = statusKey;

  const boardingCount = boardingParties.length;
  const engagedCount = marineTeams.filter(t => t.status === 'engaging').length;
  const totalTeams = marineTeams.length;
  const lockedCount = lockedDoors.length;

  document.getElementById('sb-boarding').textContent = boardingCount > 0
    ? `BOARDING: ${boardingCount} ACTIVE` : 'BOARDING: NONE';
  document.getElementById('sb-boarding').style.color = boardingCount > 0 ? C_HOSTILE : '';

  document.getElementById('sb-squads').textContent = `SQUADS: ${engagedCount}/${totalTeams} ENGAGED`;
  document.getElementById('sb-doors').textContent = `DOORS: ${lockedCount} LOCKED`;

  const armedPct = Math.round((1 - armedDecks.length / 2) * 100);
  document.getElementById('sb-armoury').textContent = `ARMOURY: ${armedPct}%`;

  const totalRooms = Object.keys(layout).length || 20;
  const damagedSensors = Object.values(sensorStatus).filter(s => s === 'damaged').length;
  const sensorPct = Math.round(((totalRooms - damagedSensors) / totalRooms) * 100);
  document.getElementById('sb-sensors').textContent = `SENSORS: ${sensorPct}%`;

  boardingStatusEl.textContent = isBoarding || boardingCount > 0 ? 'BOARDING ACTIVE' : 'STANDBY';
  boardingStatusEl.className = isBoarding || boardingCount > 0
    ? 'text-data c-hostile boarding-active' : 'text-data text-dim';
}

function renderAll(force = false) {
  draw();
  if (force) {
    renderAlerts(true);
    renderTeams(true);
  } else {
    guardedRenderAlerts();
    guardedRenderTeams();
  }
  renderBoardingIntel(force);
  renderStatusBar(force);
}

const scheduleRenderAll = createRenderScheduler(() => renderAll(), 333);

// ---------------------------------------------------------------------------
// Canvas click
// ---------------------------------------------------------------------------

canvas.addEventListener('click', (e) => {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const px = (e.clientX - rect.left) * scaleX;
  const py = (e.clientY - rect.top) * scaleY;

  const roomId = roomAtPoint(px, py);
  if (!roomId) return;

  // If a marine team is selected, send it to the clicked room
  if (selectedTeamId) {
    send('security.send_team', { team_id: selectedTeamId, destination: roomId });
    selectedTeamId = null;
    renderAll(true);
    return;
  }

  // Legacy squad move
  if (selectedSquadId) {
    send('security.move_squad', { squad_id: selectedSquadId, room_id: roomId });
    selectedSquadId = null;
    renderAll(true);
    return;
  }

  // Select room
  selectedRoomId = selectedRoomId === roomId ? null : roomId;
  renderAll(true);
});

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

document.getElementById('btn-lock')?.addEventListener('click', () => {
  if (selectedRoomId) send('security.lock_door', { room_id: selectedRoomId });
});

document.getElementById('btn-unlock')?.addEventListener('click', () => {
  if (selectedRoomId) send('security.unlock_door', { room_id: selectedRoomId });
});

document.getElementById('sel-lockdown')?.addEventListener('change', function () {
  const val = this.value; this.value = '';
  if (val === 'deck' && selectedRoomId) {
    const r = layout[selectedRoomId];
    if (r) send('security.lockdown_deck', { deck: r.deck_number || parseInt(r.deck) || 1 });
  } else if (val === 'ship') send('security.lockdown_all', {});
  else if (val === 'lift_deck' && selectedRoomId) {
    const r = layout[selectedRoomId];
    if (r) send('security.lift_lockdown', { deck: r.deck_number || parseInt(r.deck) || 1 });
  } else if (val === 'lift_all') send('security.lift_lockdown', { all: true });
});

document.getElementById('sel-bulkhead')?.addEventListener('change', function () {
  const val = this.value; this.value = '';
  const m = val.match(/(seal|unseal)_(\d)_(\d)/);
  if (!m) return;
  const type = m[1] === 'seal' ? 'security.seal_bulkhead' : 'security.unseal_bulkhead';
  send(type, { deck_above: parseInt(m[2]), deck_below: parseInt(m[3]) });
});

document.getElementById('sel-arm')?.addEventListener('change', function () {
  const val = this.value; this.value = '';
  const m = val.match(/(arm|disarm)_(\d)/);
  if (!m) return;
  const type = m[1] === 'arm' ? 'security.arm_crew' : 'security.disarm_crew';
  send(type, { deck: parseInt(m[2]) });
});

document.getElementById('sel-quarantine')?.addEventListener('change', function () {
  const val = this.value; this.value = '';
  if (val === 'room' && selectedRoomId) send('security.quarantine_room', { room_id: selectedRoomId });
  else if (val === 'lift' && selectedRoomId) send('security.lift_quarantine', { room_id: selectedRoomId });
});

document.getElementById('sel-alert')?.addEventListener('change', function () {
  const val = this.value; this.value = '';
  if (!selectedRoomId) return;
  const r = layout[selectedRoomId];
  if (r && val) send('security.set_deck_alert', { deck: r.deck_number || parseInt(r.deck) || 1, level: val });
});

// Populate quarantine and alert selects
function populateSelects() {
  const qSel = document.getElementById('sel-quarantine');
  if (qSel && qSel.options.length <= 1) {
    qSel.innerHTML = '<option value="">QUARANTINE ▼</option>';
    qSel.innerHTML += '<option value="room">QUARANTINE ROOM</option>';
    qSel.innerHTML += '<option value="lift">LIFT QUARANTINE</option>';
  }
  const aSel = document.getElementById('sel-alert');
  if (aSel && aSel.options.length <= 1) {
    aSel.innerHTML = '<option value="">SET ALERT ▼</option>';
    for (const lvl of ['normal', 'caution', 'combat', 'evacuate']) {
      aSel.innerHTML += `<option value="${lvl}">${lvl.toUpperCase()}</option>`;
    }
  }
}

// ---------------------------------------------------------------------------
// Keyboard shortcuts
// ---------------------------------------------------------------------------

document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  switch (e.key.toLowerCase()) {
    case 'l': if (selectedRoomId) send('security.lock_door', { room_id: selectedRoomId }); break;
    case 'u': if (selectedRoomId) send('security.unlock_door', { room_id: selectedRoomId }); break;
    case 'q': if (selectedRoomId) send('security.quarantine_room', { room_id: selectedRoomId }); break;
    case 'tab':
      e.preventDefault();
      if (marineTeams.length > 0) {
        const idx = marineTeams.findIndex(t => t.id === selectedTeamId);
        selectedTeamId = marineTeams[(idx + 1) % marineTeams.length].id;
        renderAll(true);
      }
      break;
  }
});

// ---------------------------------------------------------------------------
// WebSocket handlers
// ---------------------------------------------------------------------------

function handleGameStarted(payload) {
  standbyEl.style.display = 'none';
  for (const el of document.querySelectorAll('[data-security-main]')) el.style.display = '';
  if (payload.mission_name) missionLabelEl.textContent = payload.mission_name;

  _shipClass = payload.ship_class || '';

  if (payload.interior_layout) {
    layout = payload.interior_layout;
    _computeGeometry(layout);
  }

  // Load SVG silhouette
  if (_shipClass) {
    _hullImg = new Image();
    _hullImg.onload = () => draw();
    _hullImg.src = `/client/shared/silhouettes/${_shipClass}.svg`;
  }

  _populateDeckControls();
  showBriefing(payload.mission_name, payload.briefing_text);
  populateSelects();
  renderAll(true);
}

function handleInteriorState(payload) {
  isBoarding       = payload.is_boarding || false;
  squads           = payload.squads || [];
  intruders        = payload.intruders || [];
  roomsState       = payload.rooms || {};
  marineTeams      = payload.marine_teams || [];
  boardingParties  = payload.boarding_parties || [];
  lockedDoors      = payload.locked_doors || [];
  breachedDoors    = payload.breached_doors || [];
  sealedBulkheads  = payload.sealed_bulkheads || [];
  deckAlerts       = payload.deck_alerts || {};
  armedDecks       = payload.armed_decks || [];
  quarantinedRooms = payload.quarantined_rooms || [];
  sensorStatus     = payload.sensor_status || {};
  scheduleRenderAll();
}

function handleHullHit() {
  SoundBank.play('hull_hit');
  stationEl.classList.add('hit');
  setTimeout(() => stationEl.classList.remove('hit'), HIT_FLASH_MS);
}

// ---------------------------------------------------------------------------
// Incident log (playtest fix 6)
// ---------------------------------------------------------------------------

const MAX_INCIDENTS = 8;
const _incidents = [];

function handleSecurityIncident(payload) {
  _incidents.unshift({
    incident: payload.incident || 'unknown',
    message: payload.message || 'Unknown incident.',
    deck: payload.deck || '',
    time: Date.now(),
  });
  if (_incidents.length > MAX_INCIDENTS) _incidents.length = MAX_INCIDENTS;
  renderIncidentLog();
  SoundBank.play('alert');
}

function renderIncidentLog() {
  const el = document.getElementById('incident-log');
  if (!el) return;
  if (_incidents.length === 0) {
    el.innerHTML = '<p class="text-dim text-label">No incidents reported.</p>';
    return;
  }
  el.innerHTML = '';
  for (const inc of _incidents) {
    const row = document.createElement('div');
    row.className = 'incident-row';
    const age = Math.round((Date.now() - inc.time) / 1000);
    const ageStr = age < 60 ? `${age}s ago` : `${Math.floor(age / 60)}m ago`;
    row.innerHTML = `
      <span class="incident-type text-label">${inc.incident.replace(/_/g, ' ').toUpperCase()}</span>
      <span class="incident-age text-dim">${ageStr}</span>
      <p class="incident-msg text-body">${inc.message}</p>
    `;
    el.appendChild(row);
  }
}

// Refresh incident ages every 10 seconds.
setInterval(renderIncidentLog, 10_000);

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  canvas.width = _canvasW;
  canvas.height = _canvasH;

  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();
  });

  on('game.started',            handleGameStarted);
  on('security.interior_state', handleInteriorState);
  on('ship.alert_changed',      (p) => setAlertLevel(p.level));
  on('ship.hull_hit',           handleHullHit);
  on('game.over',               (p) => { SoundBank.play(p.result === 'victory' ? 'victory' : 'defeat'); showGameOver(p.result, p.stats); });
  on('security.boarding_alert', () => SoundBank.play('boarding_alert'));
  on('security.incident', handleSecurityIncident);

  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();
  initRoleBar(send, 'security');
  initCrewRoster(send);

  on('lobby.welcome', () => {
    const name = sessionStorage.getItem('player_name') || 'SECURITY';
    send('lobby.claim_role', { role: 'security', player_name: name });
  });

  populateSelects();
  connect();
}

document.addEventListener('DOMContentLoaded', init);
