/**
 * Starbridge — Security Station
 *
 * Renders the ship interior as a room grid canvas. During boarding events,
 * shows marine squad tokens (blue) and intruder tokens (red, fog-of-war
 * filtered by the server). Supports click-to-select-squad + click-to-move
 * and door toggle via the sidebar.
 *
 * Planning phase (tactical_positioning puzzle):
 *   puzzle.started (tactical_positioning) — show threat markers, countdown,
 *                                           COMMIT POSITIONS button
 *   puzzle.result                         — hide planning UI, boarding begins
 *
 * Server messages received:
 *   game.started              — show UI, store static interior_layout
 *   security.interior_state   — squads, intruders, room states (every tick)
 *   puzzle.started            — planning phase overlay (tactical_positioning)
 *   puzzle.result             — planning phase ends
 *   ship.alert_changed        — update station alert colour
 *   ship.hull_hit             — hit-flash border
 *   game.over                 — defeat/victory overlay
 *
 * Server messages sent:
 *   lobby.claim_role          { role: 'security', player_name }
 *   security.move_squad       { squad_id, room_id }
 *   security.toggle_door      { squad_id, room_id }
 *   puzzle.submit             { puzzle_id, submission: { confirmed: true } }
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import {
  setStatusDot, setAlertLevel, showBriefing, showGameOver,
} from '../shared/ui_components.js';
import { SoundBank } from '../shared/audio.js';
import '../shared/audio_events.js';
import { wireButtonSounds } from '../shared/audio_ui.js';
import { registerHelp, initHelpOverlay } from '../shared/help_overlay.js';
import { initRoleBar } from '../shared/role_bar.js';

registerHelp([
  { selector: '#ship-canvas',       text: 'Ship interior — rooms shown with squad (blue) and intruder (red) tokens.', position: 'right' },
  { selector: '#squad-list',        text: 'Marine squads — click to select, then click a room to move.', position: 'left' },
  { selector: '#btn-toggle-door',   text: 'Toggle door — seal/unseal adjacent room to control intruder movement.', position: 'above' },
  { selector: '#intruder-list',     text: 'Known intruder positions — updated from adjacent marine squads.', position: 'left' },
]);

// ---------------------------------------------------------------------------
// Canvas constants
// ---------------------------------------------------------------------------

const ROOM_W    = 120;
const ROOM_H    = 70;
const MARGIN    = 40;
const GAP       = 8;
// 4 columns, 5 rows
const CANVAS_W  = MARGIN * 2 + 4 * (ROOM_W + GAP) - GAP;  // 584
const CANVAS_H  = MARGIN * 2 + 5 * (ROOM_H + GAP) - GAP;  // 462

const SQUAD_R   = 13;   // marine squad token radius
const INTRUDER_R = 9;   // intruder token radius
const HIT_FLASH_MS = 500;

// Fixed palette (matches STYLE_GUIDE — does not shift with alert level)
const C_BG       = '#0a0a0a';
const C_PRIMARY  = '#00ff41';
const C_FRIENDLY = '#00aaff';
const C_HOSTILE  = '#ff3333';
const C_NEUTRAL  = '#888888';
const C_WARN     = '#ffb000';
const C_FIRE     = '#ff6600';
const C_DIM      = 'rgba(0,255,65,0.25)';
const C_CONN     = 'rgba(0,255,65,0.18)';

// ---------------------------------------------------------------------------
// Hull geometry constants
// ---------------------------------------------------------------------------

const HULL_CX = CANVAS_W / 2;   // 292 — horizontal centre of canvas

/**
 * Hull polygon vertices (bow = top, stern = bottom, clockwise).
 * Designed to contain the 4-col × 5-row room grid (x=40..544, y=40..422)
 * with ~16 px margin on each side.
 */
const HULL_VERTICES = [
  [292,   5],  // bow tip
  [160,  38],  // left bow shoulder
  [ 24,  96],  // left upper flank
  [ 16, 200],  // left amidships (widest)
  [ 24, 332],  // left lower flank
  [ 60, 422],  // left stern quarter
  [148, 448],  // left stern
  [292, 454],  // stern centre
  [436, 448],  // right stern
  [524, 422],  // right stern quarter
  [560, 332],  // right lower flank
  [568, 200],  // right amidships
  [560,  96],  // right upper flank
  [424,  38],  // right bow shoulder
];

/** Y positions of deck separator ribs (midpoint between consecutive row gaps). */
const DECK_BOUNDARIES_Y = [114, 192, 270, 348];

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const statusDotEl    = document.querySelector('[data-status-dot]');
const statusLabelEl  = document.querySelector('[data-status-label]');
const standbyEl      = document.querySelector('[data-standby]');
const secMainEl      = document.querySelector('[data-security-main]');
const missionLabelEl = document.getElementById('mission-label');
const stationEl      = document.querySelector('.station-container');

const canvas          = document.getElementById('ship-canvas');
const ctx             = canvas.getContext('2d');
const boardingStatusEl = document.getElementById('boarding-status');
const selectionHintEl  = document.getElementById('selection-hint');
const squadListEl      = document.getElementById('squad-list');
const intruderListEl   = document.getElementById('intruder-list');
const doorControlEl    = document.getElementById('door-control');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** room_id → { name, deck, col, row, connections[] } — static, from game.started */
let layout = {};
/** room_id → { state, door_sealed } — dynamic, from interior_state */
let roomsState = {};
/** [ { id, room_id, health, action_points, count } ] */
let squads = [];
/** [ { id, room_id, health, objective_id } ] — FOW-filtered by server */
let intruders = [];
let isBoarding = false;
let selectedSquadId = null;

// Planning phase state (tactical_positioning puzzle)
let planningPuzzleId   = null;   // active puzzle id, or null
let planningThreats    = [];     // [{ id, room_id, objective_id }]
let planningTimeLimit  = 0;
let planningCountdown  = 0;
let _planningInterval  = null;   // setInterval handle for countdown

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

function roomPixel(col, row) {
  return {
    x: MARGIN + col * (ROOM_W + GAP),
    y: MARGIN + row * (ROOM_H + GAP),
  };
}

function roomCenter(col, row) {
  const { x, y } = roomPixel(col, row);
  return { x: x + ROOM_W / 2, y: y + ROOM_H / 2 };
}

/** Return room_id at canvas pixel (px, py), or null. */
function roomAtPoint(px, py) {
  for (const [roomId, r] of Object.entries(layout)) {
    const { x, y } = roomPixel(r.col, r.row);
    if (px >= x && px <= x + ROOM_W && py >= y && py <= y + ROOM_H) {
      return roomId;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Hull rendering — ship-shaped background
// ---------------------------------------------------------------------------

/** Trace the hull polygon onto the current ctx path (does not stroke/fill). */
function hullPath() {
  ctx.beginPath();
  ctx.moveTo(HULL_VERTICES[0][0], HULL_VERTICES[0][1]);
  for (let i = 1; i < HULL_VERTICES.length; i++) {
    ctx.lineTo(HULL_VERTICES[i][0], HULL_VERTICES[i][1]);
  }
  ctx.closePath();
}

/** Draw the ship hull silhouette: dark interior fill + glowing edge. */
function drawHull() {
  ctx.save();

  // Dark hull interior
  hullPath();
  ctx.fillStyle = '#030d05';
  ctx.fill();

  // Armour-plate doubling — thick inner stroke (creates a recessed-edge look)
  ctx.save();
  hullPath();
  ctx.clip();
  hullPath();
  ctx.strokeStyle = 'rgba(0,255,65,0.09)';
  ctx.lineWidth   = 10;
  ctx.stroke();
  ctx.restore();

  // Outer hull edge with glow
  hullPath();
  ctx.shadowBlur   = 22;
  ctx.shadowColor  = 'rgba(0,255,65,0.5)';
  ctx.strokeStyle  = 'rgba(0,255,65,0.6)';
  ctx.lineWidth    = 1.5;
  ctx.stroke();
  ctx.shadowBlur = 0;

  ctx.restore();
}

/** Draw decorative structural elements: keel spine, deck ribs, orientation labels. */
function drawStructure() {
  ctx.save();

  // Clip all structure to the hull interior
  hullPath();
  ctx.clip();

  // Keel / spine line (vertical centre)
  ctx.setLineDash([5, 7]);
  ctx.strokeStyle = 'rgba(0,255,65,0.18)';
  ctx.lineWidth   = 1;
  ctx.beginPath();
  ctx.moveTo(HULL_CX, 10);
  ctx.lineTo(HULL_CX, 450);
  ctx.stroke();

  // Deck separator ribs (horizontal dashed lines at row boundaries)
  for (const y of DECK_BOUNDARIES_Y) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(CANVAS_W, y);
    ctx.stroke();
  }
  ctx.setLineDash([]);

  // Orientation labels
  ctx.font         = '7px "Share Tech Mono", monospace';
  ctx.fillStyle    = 'rgba(0,255,65,0.28)';
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'top';
  ctx.fillText('BOW', HULL_CX, 10);
  ctx.textBaseline = 'bottom';
  ctx.fillText('STERN', HULL_CX, 448);

  // PORT / STBD side labels (rotated)
  ctx.font      = '6px "Share Tech Mono", monospace';
  ctx.fillStyle = 'rgba(0,255,65,0.16)';
  ctx.textBaseline = 'middle';

  ctx.save();
  ctx.translate(12, CANVAS_H / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('PORT', 0, 0);
  ctx.restore();

  ctx.save();
  ctx.translate(CANVAS_W - 12, CANVAS_H / 2);
  ctx.rotate(Math.PI / 2);
  ctx.fillText('STBD', 0, 0);
  ctx.restore();

  // Engine exhaust glow at stern (subtle amber radial gradient)
  const eng = ctx.createRadialGradient(HULL_CX, 450, 0, HULL_CX, 450, 90);
  eng.addColorStop(0, 'rgba(255,110,0,0.10)');
  eng.addColorStop(1, 'rgba(255,110,0,0)');
  ctx.fillStyle = eng;
  ctx.fillRect(HULL_CX - 90, 368, 180, 88);

  ctx.restore();
}

// ---------------------------------------------------------------------------
// Canvas rendering
// ---------------------------------------------------------------------------

function roomStrokeColor(state) {
  switch (state) {
    case 'damaged':      return C_WARN;
    case 'decompressed': return C_NEUTRAL;
    case 'fire':         return C_FIRE;
    case 'hostile':      return C_HOSTILE;
    default:             return C_PRIMARY;
  }
}

function draw() {
  ctx.clearRect(0, 0, CANVAS_W, CANVAS_H);

  // Void background (space outside hull)
  ctx.fillStyle = C_BG;
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

  // Ship hull silhouette + structural overlays
  drawHull();
  drawStructure();

  if (Object.keys(layout).length === 0) return;

  // 1. Connection lines (drawn first, behind rooms)
  const drawnConns = new Set();
  for (const [roomId, r] of Object.entries(layout)) {
    for (const connId of r.connections) {
      const key = [roomId, connId].sort().join(':');
      if (drawnConns.has(key)) continue;
      drawnConns.add(key);

      const conn = layout[connId];
      if (!conn) continue;

      const a = roomCenter(r.col, r.row);
      const b = roomCenter(conn.col, conn.row);
      const connRoomState = roomsState[connId] || {};

      ctx.save();
      ctx.lineWidth = 1;
      if (connRoomState.door_sealed) {
        ctx.setLineDash([3, 4]);
        ctx.strokeStyle = 'rgba(255,51,51,0.4)';
      } else {
        ctx.setLineDash([]);
        ctx.strokeStyle = C_CONN;
      }
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      ctx.restore();
    }
  }

  // 2. Rooms — fill, border, sealed indicator
  const selectedSquad = squads.find(s => s.id === selectedSquadId);
  for (const [roomId, r] of Object.entries(layout)) {
    const { x, y } = roomPixel(r.col, r.row);
    const rs = roomsState[roomId] || { state: 'normal', door_sealed: false };
    const color = roomStrokeColor(rs.state);

    const isSelectedRoom = selectedSquad && selectedSquad.room_id === roomId;
    const isTargetable   = selectedSquadId && !isSelectedRoom;

    // Room fill
    if (isSelectedRoom) {
      ctx.fillStyle = 'rgba(0,170,255,0.08)';
    } else if (isTargetable) {
      ctx.fillStyle = 'rgba(0,255,65,0.04)';
    } else {
      ctx.fillStyle = 'rgba(0,255,65,0.02)';
    }
    ctx.fillRect(x, y, ROOM_W, ROOM_H);

    // Room border
    ctx.strokeStyle = isSelectedRoom ? C_FRIENDLY : color;
    ctx.lineWidth   = isSelectedRoom ? 2 : 1;
    ctx.strokeRect(x, y, ROOM_W, ROOM_H);

    // Sealed door indicator: small filled square in top-right corner
    if (rs.door_sealed) {
      ctx.fillStyle = C_HOSTILE;
      ctx.fillRect(x + ROOM_W - 7, y + 1, 6, 6);
    }

    // 3. Room name label
    ctx.fillStyle    = isSelectedRoom ? C_FRIENDLY : color;
    ctx.font         = '9px "Share Tech Mono", monospace';
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'top';
    const label = r.name.length > 15 ? r.name.slice(0, 14) + '…' : r.name;
    ctx.fillText(label, x + ROOM_W / 2, y + 5);

    // Deck sub-label (dimmer, smaller)
    ctx.fillStyle = 'rgba(0,255,65,0.35)';
    ctx.font      = '8px "Share Tech Mono", monospace';
    ctx.fillText(r.deck.toUpperCase(), x + ROOM_W / 2, y + 17);
  }

  // 3.5. Planning phase threat markers
  if (planningThreats.length > 0) {
    for (const threat of planningThreats) {
      // Spawn room: orange fill + "SPAWN" label
      const spawnR = layout[threat.room_id];
      if (spawnR) {
        const { x, y } = roomPixel(spawnR.col, spawnR.row);
        ctx.fillStyle = 'rgba(255,176,0,0.12)';
        ctx.fillRect(x, y, ROOM_W, ROOM_H);
        ctx.strokeStyle = C_WARN;
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 3]);
        ctx.strokeRect(x + 1, y + 1, ROOM_W - 2, ROOM_H - 2);
        ctx.setLineDash([]);
        ctx.fillStyle = C_WARN;
        ctx.font = 'bold 8px "Share Tech Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText('THREAT', x + ROOM_W / 2, y + ROOM_H - 4);
      }
      // Objective room: red X overlay
      const objR = layout[threat.objective_id];
      if (objR) {
        const { x, y } = roomPixel(objR.col, objR.row);
        ctx.fillStyle = 'rgba(255,51,51,0.10)';
        ctx.fillRect(x, y, ROOM_W, ROOM_H);
        ctx.strokeStyle = 'rgba(255,51,51,0.6)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x + 6, y + 6);
        ctx.lineTo(x + ROOM_W - 6, y + ROOM_H - 6);
        ctx.moveTo(x + ROOM_W - 6, y + 6);
        ctx.lineTo(x + 6, y + ROOM_H - 6);
        ctx.stroke();
        ctx.fillStyle = C_HOSTILE;
        ctx.font = 'bold 8px "Share Tech Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText('OBJ', x + ROOM_W / 2, y + ROOM_H - 4);
      }
    }
  }

  // 4. Squad tokens (blue circles with count)
  for (const sq of squads) {
    const r = layout[sq.room_id];
    if (!r) continue;

    const squadsInRoom = squads.filter(s => s.room_id === sq.room_id);
    const idx = squadsInRoom.indexOf(sq);
    const spread = squadsInRoom.length > 1 ? SQUAD_R * 1.8 : 0;
    const offset = (idx - (squadsInRoom.length - 1) / 2) * spread;

    const center = roomCenter(r.col, r.row);
    const cx = center.x + offset;
    const cy = center.y + 10;

    const isSel = sq.id === selectedSquadId;

    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, SQUAD_R, 0, Math.PI * 2);
    ctx.fillStyle   = isSel ? 'rgba(0,170,255,0.35)' : 'rgba(0,170,255,0.12)';
    ctx.fill();
    ctx.strokeStyle = isSel ? '#66ccff' : C_FRIENDLY;
    ctx.lineWidth   = isSel ? 2 : 1;
    ctx.stroke();

    // Count
    ctx.fillStyle    = C_FRIENDLY;
    ctx.font         = `bold 11px "Share Tech Mono", monospace`;
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(sq.count <= 0 ? '0' : String(sq.count), cx, cy);
    ctx.restore();
  }

  // 5. Intruder tokens (red circles with !)
  for (const intr of intruders) {
    const r = layout[intr.room_id];
    if (!r) continue;

    const center = roomCenter(r.col, r.row);
    const cx = center.x;
    const cy = center.y - 14;

    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, INTRUDER_R, 0, Math.PI * 2);
    ctx.fillStyle   = 'rgba(255,51,51,0.25)';
    ctx.fill();
    ctx.strokeStyle = C_HOSTILE;
    ctx.lineWidth   = 1;
    ctx.stroke();

    ctx.fillStyle    = C_HOSTILE;
    ctx.font         = `bold 10px "Share Tech Mono", monospace`;
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('!', cx, cy);
    ctx.restore();
  }
}

// ---------------------------------------------------------------------------
// Sidebar rendering
// ---------------------------------------------------------------------------

function renderSidebar() {
  // Boarding / planning status badge
  const isPlanning = planningPuzzleId !== null;
  if (isPlanning) {
    const secs = Math.max(0, Math.ceil(planningCountdown));
    boardingStatusEl.textContent = `POSITIONING — ${secs}s`;
    boardingStatusEl.className   = 'text-data c-warn boarding-active';
  } else {
    boardingStatusEl.textContent = isBoarding ? 'BOARDING ACTIVE' : 'STANDBY';
    boardingStatusEl.className   = isBoarding
      ? 'text-data c-hostile boarding-active'
      : 'text-data text-dim';
  }

  // Selection hint
  const selSquad = squads.find(s => s.id === selectedSquadId);
  if (isPlanning && !selSquad) {
    selectionHintEl.textContent = 'Move squads to intercept — then COMMIT';
    selectionHintEl.style.color = C_WARN;
  } else if (selSquad) {
    selectionHintEl.textContent = `${selSquad.id.toUpperCase()} selected — click target room`;
    selectionHintEl.style.color = C_FRIENDLY;
  } else {
    selectionHintEl.textContent = 'Click a squad token to select';
    selectionHintEl.style.color = '';
  }

  // Squad cards
  squadListEl.innerHTML = '';
  if (squads.length === 0) {
    const p = document.createElement('p');
    p.className   = 'text-dim text-label squad-list__empty';
    p.textContent = isBoarding ? 'No squads deployed' : '—';
    squadListEl.appendChild(p);
  }
  for (const sq of squads) {
    const isSel    = sq.id === selectedSquadId;
    const isElim   = sq.count <= 0;
    const healthPct = Math.max(0, sq.health);
    const apPct     = Math.max(0, (sq.action_points / 10) * 100);
    const roomName  = layout[sq.room_id]?.name || sq.room_id;

    let cardClass = 'squad-card';
    if (isSel)  cardClass += ' squad-card--selected';
    if (isElim) cardClass += ' squad-card--eliminated';

    const hpClass = healthPct < 50 ? 'gauge__fill--danger'
                  : healthPct < 75 ? 'gauge__fill--warn'
                  : '';

    const card = document.createElement('div');
    card.className = cardClass;
    card.innerHTML = `
      <div class="squad-card__header">
        <span class="text-label c-friendly">${sq.id.toUpperCase()}</span>
        <span class="text-data ${isElim ? 'text-dim' : 'c-friendly'}">${sq.count} MBR</span>
      </div>
      <div class="squad-card__location text-label text-dim">${roomName.toUpperCase()}</div>
      <div class="squad-bar-row">
        <span class="text-label">HP</span>
        <div class="squad-bar gauge">
          <div class="gauge__fill ${hpClass}" style="width:${healthPct}%"></div>
        </div>
        <span class="text-data">${Math.round(sq.health)}</span>
      </div>
      <div class="squad-bar-row">
        <span class="text-label">AP</span>
        <div class="squad-bar gauge">
          <div class="gauge__fill" style="width:${apPct}%"></div>
        </div>
        <span class="text-data">${sq.action_points.toFixed(1)}</span>
      </div>
    `;

    if (!isElim) {
      card.addEventListener('click', () => {
        selectedSquadId = (selectedSquadId === sq.id) ? null : sq.id;
        draw();
        renderSidebar();
      });
    }
    squadListEl.appendChild(card);
  }

  // Door control (boarding) / COMMIT button (planning)
  if (isPlanning) {
    doorControlEl.style.display = '';
    doorControlEl.innerHTML = `
      <span class="text-label c-warn">PLANNING PHASE</span>
      <button class="fire-btn" id="btn-commit-positions" style="margin-top:0.3rem">
        COMMIT POSITIONS
      </button>
    `;
    document.getElementById('btn-commit-positions')?.addEventListener('click', () => {
      if (!planningPuzzleId) return;
      send('puzzle.submit', {
        puzzle_id: planningPuzzleId,
        submission: { confirmed: true },
      });
    });
  } else if (selSquad && isBoarding) {
    doorControlEl.style.display = '';
    doorControlEl.innerHTML = `
      <span class="text-label">DOOR CONTROL</span>
      <div class="door-control__row">
        <select id="door-room-select" class="door-select"></select>
        <button class="fire-btn fire-btn--small" id="btn-toggle-door">TOGGLE</button>
      </div>
    `;
    const newSelect = document.getElementById('door-room-select');
    const newToggleBtn = document.getElementById('btn-toggle-door');
    const squadRoomDef = layout[selSquad.room_id];
    if (squadRoomDef && newSelect) {
      const candidates = [selSquad.room_id, ...squadRoomDef.connections];
      for (const roomId of candidates) {
        const opt = document.createElement('option');
        opt.value       = roomId;
        const rs        = roomsState[roomId] || {};
        const sealTag   = rs.door_sealed ? ' [SEALED]' : '';
        opt.textContent = ((layout[roomId]?.name || roomId) + sealTag).toUpperCase();
        newSelect.appendChild(opt);
      }
    }
    newToggleBtn?.addEventListener('click', () => {
      if (!selectedSquadId) return;
      const targetRoomId = newSelect?.value;
      if (!targetRoomId) return;
      send('security.toggle_door', { squad_id: selectedSquadId, room_id: targetRoomId });
    });
  } else {
    doorControlEl.style.display = 'none';
  }

  // Intruder list
  intruderListEl.innerHTML = '';
  if (intruders.length === 0) {
    const p = document.createElement('p');
    p.className   = 'text-dim text-label intruder-list__empty';
    p.textContent = isBoarding ? 'No contacts' : '—';
    intruderListEl.appendChild(p);
    return;
  }
  for (const intr of intruders) {
    const roomName = layout[intr.room_id]?.name     || intr.room_id;
    const objName  = layout[intr.objective_id]?.name || intr.objective_id;
    const hpPct    = Math.max(0, intr.health);

    const item = document.createElement('div');
    item.className = 'intruder-item';
    item.innerHTML = `
      <div class="intruder-item__row">
        <span class="text-label c-hostile">${intr.id.toUpperCase()}</span>
        <span class="text-data c-hostile">${Math.round(intr.health)}%</span>
      </div>
      <div class="intruder-detail-row">
        <span class="text-label text-dim">LOC:</span>
        <span class="text-label">${roomName.toUpperCase()}</span>
      </div>
      <div class="intruder-detail-row">
        <span class="text-label text-dim">OBJ:</span>
        <span class="text-label">${objName.toUpperCase()}</span>
      </div>
      <div class="intruder-hp gauge" style="margin-top:0.2rem">
        <div class="gauge__fill gauge__fill--danger" style="width:${hpPct}%"></div>
      </div>
    `;
    intruderListEl.appendChild(item);
  }
}

// ---------------------------------------------------------------------------
// Canvas click interaction
// ---------------------------------------------------------------------------

canvas.addEventListener('click', (e) => {
  const rect   = canvas.getBoundingClientRect();
  const scaleX = canvas.width  / rect.width;
  const scaleY = canvas.height / rect.height;
  const px = (e.clientX - rect.left) * scaleX;
  const py = (e.clientY - rect.top)  * scaleY;

  const roomId = roomAtPoint(px, py);
  if (!roomId) return;

  if (selectedSquadId) {
    const selSquad = squads.find(s => s.id === selectedSquadId);
    if (selSquad && selSquad.room_id === roomId) {
      // Click on own room → deselect
      selectedSquadId = null;
    } else {
      // Click on another room → move (works during both planning and boarding)
      send('security.move_squad', { squad_id: selectedSquadId, room_id: roomId });
      selectedSquadId = null;
    }
  } else {
    // Select the first non-eliminated squad in this room
    const found = squads.find(s => s.room_id === roomId && s.count > 0);
    if (found) selectedSquadId = found.id;
  }

  draw();
  renderSidebar();
});

// ---------------------------------------------------------------------------
// WebSocket handlers
// ---------------------------------------------------------------------------

function handleGameStarted(payload) {
  standbyEl.style.display  = 'none';
  secMainEl.style.display  = '';
  if (payload.mission_name)    missionLabelEl.textContent = payload.mission_name;
  if (payload.interior_layout) layout = payload.interior_layout;
  showBriefing(payload.mission_name, payload.briefing_text);
  draw();
  renderSidebar();
}

function handleInteriorState(payload) {
  isBoarding  = payload.is_boarding || false;
  squads      = payload.squads     || [];
  intruders   = payload.intruders  || [];
  roomsState  = payload.rooms      || {};
  draw();
  renderSidebar();
}

function handlePuzzleStarted(payload) {
  if (payload.type !== 'tactical_positioning') return;
  planningPuzzleId  = payload.puzzle_id;
  planningThreats   = payload.data?.intruder_threats || [];
  planningTimeLimit = payload.time_limit || 60;
  planningCountdown = planningTimeLimit;

  // Client-side countdown (server is authoritative; this is display only).
  if (_planningInterval) clearInterval(_planningInterval);
  _planningInterval = setInterval(() => {
    planningCountdown -= 0.1;
    if (planningCountdown <= 0) {
      clearInterval(_planningInterval);
      _planningInterval = null;
    }
    renderSidebar();  // update countdown badge
  }, 100);

  draw();
  renderSidebar();
}

function handlePuzzleResult(payload) {
  if (payload.puzzle_id !== planningPuzzleId) return;
  // Planning phase ended — clear state.
  planningPuzzleId = null;
  planningThreats  = [];
  if (_planningInterval) { clearInterval(_planningInterval); _planningInterval = null; }
  draw();
  renderSidebar();
}

function handleHullHit() {
  SoundBank.play('hull_hit');
  stationEl.classList.add('hit');
  setTimeout(() => stationEl.classList.remove('hit'), HIT_FLASH_MS);
}

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  canvas.width  = CANVAS_W;
  canvas.height = CANVAS_H;

  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();
  });

  on('game.started',            handleGameStarted);
  on('security.interior_state', handleInteriorState);
  on('puzzle.started',          handlePuzzleStarted);
  on('puzzle.result',           handlePuzzleResult);
  on('ship.alert_changed',      (p) => setAlertLevel(p.level));
  on('ship.hull_hit',           handleHullHit);
  on('game.over',               (p) => { SoundBank.play(p.result === 'victory' ? 'victory' : 'defeat'); showGameOver(p.result, p.stats); });
  on('security.boarding_started', () => SoundBank.play('boarding_alert'));

  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();
  initRoleBar(send, 'security');

  on('lobby.welcome', () => {
    const name = sessionStorage.getItem('player_name') || 'SECURITY';
    send('lobby.claim_role', { role: 'security', player_name: name });
  });

  connect();
}

document.addEventListener('DOMContentLoaded', init);
