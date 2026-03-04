/**
 * Starbridge — Hazard Control Station (B.7 Overhaul)
 *
 * Three-panel layout with canvas interior map, deck status cards,
 * contextual action buttons, active hazard list, event log, and
 * 10 procedural audio cues.
 *
 * Server messages received:
 *   game.started              — reveal UI; store interior layout
 *   hazard_control.state      — DC state (fires, DCTs, sections, bulkheads, power, pods)
 *   hazard_control.atmosphere — per-room atmosphere (O2, pressure, temp, contamination)
 *   ship.state                — resources (suppressant), crew, systems (life support)
 *   ship.alert_changed        — update alert colour
 *   ship.hull_hit             — hit-flash border
 *   game.over                 — victory/defeat overlay
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
import { createRenderScheduler, guardInteraction } from '../shared/render_scheduler.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const HIT_FLASH_MS = 500;
const MAX_LOG = 50;

const OVERLAY_MODES = ['ALL', 'ATMO', 'TEMP', 'CONTAM', 'STRUCT', 'FIRE'];
const SEV_NAMES = ['SAFE', 'CAUTION', 'HAZARDOUS', 'CRITICAL', 'UNINHABITABLE'];
const SEV_CSS   = ['safe', 'caution', 'hazardous', 'critical', 'uninhabitable'];

const DECK_LABELS = {
  bridge: 'Bridge', sensors: 'Sensors', weapons: 'Weapons',
  shields: 'Shields', engineering: 'Engineering', medical: 'Medical',
};

// Canvas drawing
const ROOM_PAD   = 30;
const MIN_ROOM_W = 80;
const MIN_ROOM_H = 44;
const ROOM_RAD   = 4;
const CONN_HIT   = 8;   // click hit-test threshold for connections
const LABEL_FONT = '10px monospace';
const DECK_FONT  = 'bold 11px monospace';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _allRooms   = {};     // room_id → {name, deck, deck_number, col, row, connections}
let _dcState    = null;   // hazard_control.state payload
let _atmState   = null;   // hazard_control.atmosphere payload
let _shipState  = null;   // ship.state payload
let _prevDcState  = null;
let _prevAtmState = null;

let _selectedRoom = null; // room_id or null
let _selectedConn = null; // [roomA, roomB] sorted or null
let _overlayMode  = 'ALL';
let _highlightDeck = null;

let _eventLog = [];       // [{text, cls}]
let _send     = null;
let _gameActive = false;

// Canvas geometry (recomputed on resize)
let _canvas, _ctx;
let _canvasW = 0, _canvasH = 0;
let _roomRects = {};      // room_id → {x, y, w, h, cx, cy}
let _connLines = [];      // [{x1,y1,x2,y2,roomA,roomB,mx,my}]

// Animation
let _rafId     = null;
let _animTime  = 0;

// Audio
let _audioCtx = null;
let _audioOut = null;

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);

const statusDotEl   = document.querySelector('[data-status-dot]');
const statusLabelEl = document.querySelector('[data-status-label]');
const standbyEl     = document.querySelector('[data-standby]');
const hcMainEl      = document.querySelector('[data-hc-main]');
const missionLabelEl = $('mission-label');
const stationEl     = document.querySelector('.station-container');

const deckListEl    = $('hc-deck-list');
const overlayBarEl  = $('hc-overlay-bar');
const actionsEl     = $('hc-actions');
const actionsTitleEl = $('hc-actions-title');
const hazardsEl     = $('hc-hazards');
const logEl         = $('hc-log');

// Bottom bar
const elSupp   = $('hc-suppressant');
const elTeams  = $('hc-teams');
const elFF     = $('hc-forcefields');
const elLS     = $('hc-lifesupport');
const elWorst  = $('hc-worstdeck');

// ---------------------------------------------------------------------------
// Render throttle + interaction guard
// ---------------------------------------------------------------------------

const guardedRenderDeckCards = guardInteraction(() => renderDeckCards(), deckListEl);
const guardedRenderActions  = guardInteraction(() => renderActions(), actionsEl);

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

function deckLabel(deckName) {
  return DECK_LABELS[deckName] || deckName.toUpperCase();
}

function roomName(roomId) {
  const r = _allRooms[roomId];
  return r ? r.name : roomId;
}

function connKey(a, b) {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

function sortedPair(a, b) {
  return a < b ? [a, b] : [b, a];
}

function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

function lerp(a, b, t) { return a + (b - a) * clamp(t, 0, 1); }

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function lerpColor(c1, c2, t) {
  const r1 = parseInt(c1.slice(1, 3), 16), g1 = parseInt(c1.slice(3, 5), 16), b1 = parseInt(c1.slice(5, 7), 16);
  const r2 = parseInt(c2.slice(1, 3), 16), g2 = parseInt(c2.slice(3, 5), 16), b2 = parseInt(c2.slice(5, 7), 16);
  const r = Math.round(lerp(r1, r2, t));
  const g = Math.round(lerp(g1, g2, t));
  const b = Math.round(lerp(b1, b2, t));
  return `rgb(${r},${g},${b})`;
}

// ---------------------------------------------------------------------------
// Overlay colour functions
// ---------------------------------------------------------------------------

function atmoColor(roomId) {
  const atm = _atmState?.rooms?.[roomId];
  const o2 = atm?.o2 ?? 21;
  if (o2 >= 19) return '#2a9d2a';
  if (o2 >= 15) return '#cccc00';
  if (o2 >= 10) return '#ff8800';
  return '#ff2020';
}

function tempColor(roomId) {
  const atm = _atmState?.rooms?.[roomId];
  const t = atm?.temp ?? 20;
  if (t < 15)  return '#3366cc';
  if (t <= 25) return '#2a9d2a';
  if (t <= 40) return '#cccc00';
  if (t <= 60) return '#ff8800';
  return '#ff2020';
}

function contamColor(roomId) {
  const atm = _atmState?.rooms?.[roomId];
  const c = atm?.contam_level ?? 0;
  if (c < 5)  return '#2a9d2a';
  if (c < 20) return '#cccc00';
  if (c < 50) return '#ff8800';
  return '#ff2020';
}

function structColor(roomId) {
  const integrity = getRoomIntegrity(roomId);
  if (integrity === null) return '#2a4a2a';
  if (integrity <= 0) return '#111111';
  if (integrity < 25)  return '#ff2020';
  if (integrity < 50)  return '#ff8800';
  if (integrity < 75)  return '#cccc00';
  return '#2a9d2a';
}

function fireColor(roomId) {
  const fire = _dcState?.fires?.[roomId];
  if (!fire) return '#1a1a2a';
  const i = fire.intensity || 1;
  if (i <= 1) return '#cccc00';
  if (i <= 2) return '#ff8800';
  if (i <= 3) return '#ff2020';
  if (i <= 4) return '#ff4444';
  return '#ffffff';
}

function worstOverlayColor(roomId) {
  const colors = [atmoColor, tempColor, contamColor, structColor, fireColor];
  const priority = { '#ff2020': 4, '#ff4444': 4, '#ffffff': 5, '#111111': 5,
    '#ff8800': 3, '#cccc00': 2, '#3366cc': 1, '#2a9d2a': 0, '#2a4a2a': 0, '#1a1a2a': 0 };
  let worst = '#2a9d2a';
  let worstP = -1;
  for (const fn of colors) {
    const c = fn(roomId);
    const p = priority[c] ?? 0;
    if (p > worstP) { worst = c; worstP = p; }
  }
  return worst;
}

function getOverlayColor(roomId) {
  switch (_overlayMode) {
    case 'ATMO':   return atmoColor(roomId);
    case 'TEMP':   return tempColor(roomId);
    case 'CONTAM': return contamColor(roomId);
    case 'STRUCT': return structColor(roomId);
    case 'FIRE':   return fireColor(roomId);
    default:       return worstOverlayColor(roomId);
  }
}

// ---------------------------------------------------------------------------
// Section / integrity helpers
// ---------------------------------------------------------------------------

function getRoomSection(roomId) {
  if (!_dcState?.sections) return null;
  for (const [sid, sec] of Object.entries(_dcState.sections)) {
    if (sec.room_ids && sec.room_ids.includes(roomId)) return { id: sid, ...sec };
  }
  return null;
}

function getRoomIntegrity(roomId) {
  const sec = getRoomSection(roomId);
  return sec ? sec.integrity : null;
}

function isConnectionSealed(roomA, roomB) {
  if (!_dcState?.sealed_connections) return false;
  return _dcState.sealed_connections.some(
    ([a, b]) => (a === roomA && b === roomB) || (a === roomB && b === roomA),
  );
}

function getVentState(roomA, roomB) {
  if (!_atmState?.vents) return null;
  return _atmState.vents[connKey(roomA, roomB)] ||
         _atmState.vents[`${roomA}|${roomB}`] ||
         _atmState.vents[`${roomB}|${roomA}`] || null;
}

// ---------------------------------------------------------------------------
// Canvas: geometry
// ---------------------------------------------------------------------------

function computeRoomGeometry() {
  const entries = Object.entries(_allRooms);
  if (entries.length === 0 || !_canvasW || !_canvasH) return;

  let minCol = Infinity, maxCol = -Infinity;
  let minRow = Infinity, maxRow = -Infinity;
  for (const [, r] of entries) {
    if (r.col < minCol) minCol = r.col;
    if (r.col > maxCol) maxCol = r.col;
    if (r.row < minRow) minRow = r.row;
    if (r.row > maxRow) maxRow = r.row;
  }

  const cols = maxCol - minCol + 1;
  const rows = maxRow - minRow + 1;
  const cellW = Math.max(MIN_ROOM_W + 10, (_canvasW - 2 * ROOM_PAD) / cols);
  const cellH = Math.max(MIN_ROOM_H + 10, (_canvasH - 2 * ROOM_PAD) / rows);
  const roomW = Math.min(cellW - 10, 140);
  const roomH = Math.min(cellH - 10, 60);

  _roomRects = {};
  for (const [id, r] of entries) {
    const cx = ROOM_PAD + (r.col - minCol + 0.5) * cellW;
    const cy = ROOM_PAD + (r.row - minRow + 0.5) * cellH;
    _roomRects[id] = {
      x: cx - roomW / 2, y: cy - roomH / 2,
      w: roomW, h: roomH, cx, cy,
    };
  }

  // Build connection line list (deduplicated)
  const seen = new Set();
  _connLines = [];
  for (const [id, r] of entries) {
    for (const cid of (r.connections || [])) {
      const key = connKey(id, cid);
      if (seen.has(key) || !_roomRects[cid]) continue;
      seen.add(key);
      const a = _roomRects[id], b = _roomRects[cid];
      _connLines.push({
        x1: a.cx, y1: a.cy, x2: b.cx, y2: b.cy,
        roomA: id, roomB: cid,
        mx: (a.cx + b.cx) / 2, my: (a.cy + b.cy) / 2,
      });
    }
  }
}

function resizeCanvas() {
  if (!_canvas) return;
  const wrap = _canvas.parentElement;
  if (!wrap) return;
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;
  if (w < 1 || h < 1) return;
  const dpr = window.devicePixelRatio || 1;
  _canvas.width = w * dpr;
  _canvas.height = h * dpr;
  _canvasW = w;
  _canvasH = h;
  _ctx = _canvas.getContext('2d');
  _ctx.scale(dpr, dpr);
  computeRoomGeometry();
}

// ---------------------------------------------------------------------------
// Canvas: drawing
// ---------------------------------------------------------------------------

function drawCanvas(time) {
  if (!_ctx || !_canvasW) return;
  _animTime = time || 0;
  const ctx = _ctx;
  ctx.clearRect(0, 0, _canvasW, _canvasH);

  // Draw connections
  for (const c of _connLines) {
    const sealed = isConnectionSealed(c.roomA, c.roomB);
    const ventState = getVentState(c.roomA, c.roomB);
    const isSelConn = _selectedConn &&
      connKey(_selectedConn[0], _selectedConn[1]) === connKey(c.roomA, c.roomB);

    ctx.beginPath();
    ctx.moveTo(c.x1, c.y1);
    ctx.lineTo(c.x2, c.y2);
    ctx.lineWidth = sealed ? 3 : isSelConn ? 2.5 : 1.5;
    ctx.strokeStyle = sealed ? '#ff2020' : isSelConn ? '#00ccff' : 'rgba(255,255,255,0.15)';
    ctx.stroke();

    // Vent state label at midpoint
    if (ventState && ventState !== 'open') {
      ctx.font = '8px monospace';
      ctx.fillStyle = ventState === 'sealed' ? '#ff4444' : '#ffb000';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(ventState.toUpperCase(), c.mx, c.my - 6);
    }
  }

  // Draw rooms
  for (const [id, rect] of Object.entries(_roomRects)) {
    const color = getOverlayColor(id);
    const isSelected = id === _selectedRoom;
    const isHighlightDeck = _highlightDeck && _allRooms[id]?.deck === _highlightDeck;
    const hasFire = !!_dcState?.fires?.[id];
    const hasBreach = !!_atmState?.breaches?.[id];
    const hasDCT = !!_dcState?.active_dcts?.[id];

    // Room fill
    ctx.beginPath();
    ctx.roundRect(rect.x, rect.y, rect.w, rect.h, ROOM_RAD);
    ctx.fillStyle = hexToRgba(color, 0.35);
    ctx.fill();

    // Fire shimmer overlay
    if (hasFire) {
      const shimmer = 0.15 + 0.1 * Math.sin(_animTime * 0.004);
      ctx.fillStyle = `rgba(255, 60, 20, ${shimmer})`;
      ctx.fill();
    }

    // Breach indicator
    if (hasBreach) {
      const pulse = 0.1 + 0.08 * Math.sin(_animTime * 0.006);
      ctx.fillStyle = `rgba(80, 112, 192, ${pulse})`;
      ctx.fill();
    }

    // Border
    ctx.lineWidth = isSelected ? 2.5 : isHighlightDeck ? 1.8 : 1;
    ctx.strokeStyle = isSelected ? '#00ccff'
      : isHighlightDeck ? 'rgba(0, 204, 255, 0.5)'
      : hexToRgba(color, 0.6);
    ctx.stroke();

    // Room name
    ctx.font = LABEL_FONT;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#cccccc';
    const label = _allRooms[id]?.name || id;
    const maxChars = Math.floor(rect.w / 6.5);
    ctx.fillText(label.length > maxChars ? label.slice(0, maxChars - 1) + '…' : label,
      rect.cx, rect.cy - 5);

    // Status icons row
    const icons = [];
    if (hasFire) icons.push({ c: '#ff2020', t: 'F' + (_dcState.fires[id].intensity || '') });
    if (hasBreach) icons.push({ c: '#5070c0', t: 'B' });
    if (hasDCT) icons.push({ c: '#00ff41', t: 'R' });
    if (_atmState?.decon_teams?.[id] != null) icons.push({ c: '#aa00aa', t: 'D' });
    if (_atmState?.space_venting?.includes(id)) icons.push({ c: '#3399cc', t: 'V' });

    if (icons.length > 0) {
      ctx.font = '8px monospace';
      const totalW = icons.length * 14;
      let ix = rect.cx - totalW / 2 + 7;
      for (const ic of icons) {
        ctx.fillStyle = ic.c;
        ctx.fillText(ic.t, ix, rect.cy + 10);
        ix += 14;
      }
    }
  }
}

function animLoop(time) {
  if (!_gameActive) return;
  drawCanvas(time);
  _rafId = requestAnimationFrame(animLoop);
}

// ---------------------------------------------------------------------------
// Canvas: hit testing
// ---------------------------------------------------------------------------

function hitTestRoom(x, y) {
  for (const [id, r] of Object.entries(_roomRects)) {
    if (x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h) return id;
  }
  return null;
}

function pointToSegDist(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(px - x1, py - y1);
  let t = ((px - x1) * dx + (py - y1) * dy) / len2;
  t = clamp(t, 0, 1);
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

function hitTestConnection(x, y) {
  let best = null, bestDist = CONN_HIT + 1;
  for (const c of _connLines) {
    const d = pointToSegDist(x, y, c.x1, c.y1, c.x2, c.y2);
    if (d < bestDist) { bestDist = d; best = [c.roomA, c.roomB]; }
  }
  return best;
}

function handleCanvasClick(e) {
  if (!_canvas) return;
  const rect = _canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;

  const room = hitTestRoom(x, y);
  if (room) {
    _selectedRoom = (_selectedRoom === room) ? null : room;
    _selectedConn = null;
    renderActions();
    return;
  }

  const conn = hitTestConnection(x, y);
  if (conn) {
    const key = connKey(conn[0], conn[1]);
    const prevKey = _selectedConn ? connKey(_selectedConn[0], _selectedConn[1]) : null;
    _selectedConn = (key === prevKey) ? null : sortedPair(conn[0], conn[1]);
    _selectedRoom = null;
    renderActions();
    return;
  }

  // Click on empty space — deselect
  _selectedRoom = null;
  _selectedConn = null;
  renderActions();
}

// ---------------------------------------------------------------------------
// Overlay mode bar
// ---------------------------------------------------------------------------

function buildOverlayBar() {
  overlayBarEl.innerHTML = '';
  for (const mode of OVERLAY_MODES) {
    const btn = document.createElement('button');
    btn.className = 'hc-overlay-btn' + (mode === _overlayMode ? ' hc-overlay-btn--active' : '');
    btn.textContent = mode;
    btn.addEventListener('click', () => {
      _overlayMode = mode;
      buildOverlayBar();
    });
    overlayBarEl.appendChild(btn);
  }
}

// ---------------------------------------------------------------------------
// Deck severity computation
// ---------------------------------------------------------------------------

function computeSeverity(metrics) {
  // Returns 0=SAFE .. 4=UNINHABITABLE
  let sev = 0;
  // O2
  if (metrics.o2 < 5)       sev = Math.max(sev, 4);
  else if (metrics.o2 < 10) sev = Math.max(sev, 3);
  else if (metrics.o2 < 15) sev = Math.max(sev, 2);
  else if (metrics.o2 < 19) sev = Math.max(sev, 1);
  // Temperature
  if (metrics.temp > 80)      sev = Math.max(sev, 4);
  else if (metrics.temp > 60) sev = Math.max(sev, 3);
  else if (metrics.temp > 40) sev = Math.max(sev, 2);
  else if (metrics.temp > 30) sev = Math.max(sev, 1);
  if (metrics.temp < 0)       sev = Math.max(sev, 3);
  else if (metrics.temp < 10) sev = Math.max(sev, 2);
  // Contamination
  if (metrics.contam > 75)      sev = Math.max(sev, 4);
  else if (metrics.contam > 50) sev = Math.max(sev, 3);
  else if (metrics.contam > 20) sev = Math.max(sev, 2);
  else if (metrics.contam > 5)  sev = Math.max(sev, 1);
  // Structural
  if (metrics.structural <= 0)        sev = Math.max(sev, 4);
  else if (metrics.structural < 25)   sev = Math.max(sev, 3);
  else if (metrics.structural < 50)   sev = Math.max(sev, 2);
  else if (metrics.structural < 75)   sev = Math.max(sev, 1);
  // Fires
  if (metrics.maxFireIntensity >= 4) sev = Math.max(sev, 3);
  else if (metrics.fireCount > 2)    sev = Math.max(sev, 2);
  else if (metrics.fireCount > 0)    sev = Math.max(sev, 1);
  // Pressure
  if (metrics.pressure < 40)       sev = Math.max(sev, 4);
  else if (metrics.pressure < 70)  sev = Math.max(sev, 3);
  else if (metrics.pressure < 90)  sev = Math.max(sev, 2);
  return sev;
}

function computeDeckStatuses() {
  // Group rooms by deck name
  const byDeck = {};
  for (const [id, r] of Object.entries(_allRooms)) {
    const dk = r.deck || 'unknown';
    if (!byDeck[dk]) byDeck[dk] = { name: dk, deckNumber: r.deck_number, roomIds: [] };
    byDeck[dk].roomIds.push(id);
  }

  const decks = [];
  for (const [dk, info] of Object.entries(byDeck)) {
    const roomIds = info.roomIds;
    let o2Sum = 0, pressSum = 0, tempMax = -Infinity, contamMax = 0;
    let structMin = 100, fireCount = 0, maxFireInt = 0;
    let contamType = '';
    let count = roomIds.length;

    for (const rid of roomIds) {
      const atm = _atmState?.rooms?.[rid];
      o2Sum += atm?.o2 ?? 21;
      pressSum += atm?.pressure ?? 101;
      const t = atm?.temp ?? 20;
      if (t > tempMax) tempMax = t;
      const cl = atm?.contam_level ?? 0;
      if (cl > contamMax) { contamMax = cl; contamType = atm?.contam_type || ''; }

      const sec = getRoomSection(rid);
      if (sec && sec.integrity < structMin) structMin = sec.integrity;

      const fire = _dcState?.fires?.[rid];
      if (fire) { fireCount++; if (fire.intensity > maxFireInt) maxFireInt = fire.intensity; }
    }

    const dn = info.deckNumber;
    const crew = _shipState?.crew?.[dk];
    const power = _dcState?.deck_power?.[String(dn)];
    const battery = _dcState?.deck_batteries?.[String(dn)];

    const metrics = {
      o2: count > 0 ? o2Sum / count : 21,
      pressure: count > 0 ? pressSum / count : 101,
      temp: tempMax === -Infinity ? 20 : tempMax,
      contam: contamMax,
      contamType,
      structural: structMin,
      fireCount,
      maxFireIntensity: maxFireInt,
      crewActive: crew?.active ?? '—',
      crewTotal: crew?.total ?? '—',
      power: power != null ? power : true,
      battery: battery ?? null,
    };
    metrics.severity = computeSeverity(metrics);
    decks.push({ name: dk, deckNumber: dn, metrics, roomIds });
  }

  // Sort worst-first
  decks.sort((a, b) => b.metrics.severity - a.metrics.severity);
  return decks;
}

// ---------------------------------------------------------------------------
// Left panel: deck status cards
// ---------------------------------------------------------------------------

function renderDeckCards() {
  const decks = computeDeckStatuses();
  deckListEl.innerHTML = '';

  for (const d of decks) {
    const m = d.metrics;
    const sevIdx = m.severity;
    const sevName = SEV_NAMES[sevIdx];
    const sevCss = SEV_CSS[sevIdx];
    const isSelected = _highlightDeck === d.name;

    const card = document.createElement('div');
    card.className = `hc-deck-card hc-deck-card--${sevCss}${isSelected ? ' hc-deck-card--selected' : ''}`;
    card.addEventListener('click', () => {
      _highlightDeck = (_highlightDeck === d.name) ? null : d.name;
      renderDeckCards();
    });

    const o2Cls = m.o2 < 15 ? ' hc-metric-crit' : m.o2 < 19 ? ' hc-metric-warn' : '';
    const tempCls = m.temp > 40 ? ' hc-metric-crit' : m.temp > 30 ? ' hc-metric-warn' : '';
    const structCls = m.structural < 25 ? ' hc-metric-crit' : m.structural < 50 ? ' hc-metric-warn' : '';
    const contamCls = m.contam > 50 ? ' hc-metric-crit' : m.contam > 5 ? ' hc-metric-warn' : '';

    card.innerHTML = `
      <div class="hc-deck-name">
        <span>${deckLabel(d.name)}</span>
        <span class="hc-deck-severity hc-sev-${sevCss}">${sevName}</span>
      </div>
      <div class="hc-deck-metrics">
        <span class="${o2Cls}">O2 ${m.o2.toFixed(0)}%</span>
        <span>P ${m.pressure.toFixed(0)}kPa</span>
        <span class="${tempCls}">T ${m.temp.toFixed(0)}°C</span>
        <span class="${contamCls}">CTM ${m.contam.toFixed(0)}</span>
        <span class="${structCls}">STR ${m.structural.toFixed(0)}%</span>
        <span>FIRE ${m.fireCount}</span>
        <span>CREW ${m.crewActive}/${m.crewTotal}</span>
        <span>PWR ${m.power ? 'ON' : 'OFF'}</span>
      </div>
    `;
    deckListEl.appendChild(card);
  }

  // Update worst deck in bottom bar
  if (decks.length > 0) {
    const w = decks[0];
    elWorst.textContent = `WORST ${deckLabel(w.name)} ${SEV_NAMES[w.metrics.severity]}`;
  }
}

// ---------------------------------------------------------------------------
// Right panel: contextual action buttons
// ---------------------------------------------------------------------------

function addBtn(parent, label, cls, handler, disabled) {
  const btn = document.createElement('button');
  btn.className = `hc-action-btn${cls ? ' hc-action-btn--' + cls : ''}`;
  btn.textContent = label;
  btn.disabled = !!disabled;
  if (!disabled) btn.addEventListener('click', handler);
  parent.appendChild(btn);
}

function renderActions() {
  if (_selectedRoom) {
    renderRoomActions();
  } else if (_selectedConn) {
    renderConnectionActions();
  } else {
    actionsTitleEl.textContent = 'ACTIONS';
    actionsEl.innerHTML = '<p class="text-dim">Select a room or connection.</p>';
  }
}

function renderRoomActions() {
  const rid = _selectedRoom;
  const room = _allRooms[rid];
  if (!room) return;

  actionsTitleEl.textContent = room.name || rid;
  actionsEl.innerHTML = '';

  // Room details
  const detail = document.createElement('div');
  detail.className = 'hc-sel-detail';
  const atm = _atmState?.rooms?.[rid];
  const sec = getRoomSection(rid);
  const fire = _dcState?.fires?.[rid];
  const breach = _atmState?.breaches?.[rid];
  const dctProgress = _dcState?.active_dcts?.[rid];
  const fireTeam = _dcState?.fire_teams?.[rid];
  const decon = _atmState?.decon_teams?.[rid];
  const isVenting = _dcState?.vent_rooms?.includes(rid);
  const isSpaceVent = _atmState?.space_venting?.includes(rid);
  const roomState = _dcState?.rooms?.[rid]?.state || 'normal';

  const lines = [];
  lines.push(`Deck: ${deckLabel(room.deck)}`);
  lines.push(`Status: ${roomState.toUpperCase()}`);
  if (atm) {
    lines.push(`O2: ${atm.o2.toFixed(1)}%  P: ${atm.pressure.toFixed(0)}kPa  T: ${atm.temp.toFixed(0)}°C`);
    if (atm.contam_level > 0) lines.push(`Contam: ${atm.contam_level.toFixed(0)} (${atm.contam_type || '?'})`);
    if (atm.rad_zone && atm.rad_zone !== 'green') lines.push(`Radiation: ${atm.rad_zone.toUpperCase()}`);
  }
  if (sec) lines.push(`Integrity: ${sec.integrity.toFixed(0)}% (${sec.state})`);
  if (fire) lines.push(`Fire: intensity ${fire.intensity}`);
  if (breach) lines.push(`Breach: sev ${(breach.severity * 100).toFixed(0)}%${breach.force_field ? ' [FF]' : ''}`);
  if (dctProgress != null) lines.push(`DCT: ${(dctProgress * 100).toFixed(0)}%`);
  detail.textContent = lines.join('\n');
  actionsEl.appendChild(detail);

  // --- Action buttons ---
  const hasDamage = roomState === 'damaged' || roomState === 'fire';
  const hasDCT = dctProgress != null;

  // DCT
  addBtn(actionsEl, hasDCT ? `CANCEL DCT (${(dctProgress * 100).toFixed(0)}%)` : 'DISPATCH DCT',
    hasDCT ? 'danger' : 'primary',
    () => _send(hasDCT ? 'hazard_control.cancel_dct' : 'hazard_control.dispatch_dct', { room_id: rid }),
    !hasDCT && !hasDamage);

  // Fire actions
  if (fire) {
    addBtn(actionsEl, 'SUPPRESS FIRE', 'danger',
      () => _send('hazard_control.suppress_local', { room_id: rid }));
    if (fireTeam != null) {
      addBtn(actionsEl, 'CANCEL FIRE TEAM', 'danger',
        () => _send('hazard_control.cancel_fire_team', { room_id: rid }));
    } else {
      addBtn(actionsEl, 'DISPATCH FIRE TEAM', '',
        () => _send('hazard_control.dispatch_fire_team', { room_id: rid }));
    }
  }

  // Breach actions
  if (breach) {
    if (!breach.force_field) {
      addBtn(actionsEl, 'ACTIVATE FORCE FIELD', '',
        () => _send('hazard_control.force_field', { room_id: rid }));
    }
    if (!breach.bulkhead_sealed) {
      addBtn(actionsEl, 'SEAL BULKHEAD', '',
        () => _send('hazard_control.seal_bulkhead', { room_id: rid }));
    } else {
      addBtn(actionsEl, 'UNSEAL BULKHEAD', '',
        () => _send('hazard_control.unseal_bulkhead', { room_id: rid }));
    }
  }

  // Radiation
  if (atm && atm.rad_zone && atm.rad_zone !== 'green') {
    if (decon != null) {
      addBtn(actionsEl, 'CANCEL DECON TEAM', 'danger',
        () => _send('hazard_control.cancel_decon_team', { room_id: rid }));
    } else {
      addBtn(actionsEl, 'DEPLOY DECON TEAM', '',
        () => _send('hazard_control.dispatch_decon_team', { room_id: rid }));
    }
  }

  // Venting
  if (isVenting) {
    addBtn(actionsEl, 'CANCEL VENT', '',
      () => _send('hazard_control.cancel_vent', { room_id: rid }));
  } else {
    addBtn(actionsEl, 'VENT ROOM', '',
      () => _send('hazard_control.vent_room', { room_id: rid }));
  }

  // Space vent
  if (isSpaceVent) {
    addBtn(actionsEl, 'CANCEL SPACE VENT', 'danger',
      () => _send('hazard_control.cancel_space_vent', { room_id: rid }));
  } else {
    addBtn(actionsEl, 'EMERGENCY VENT TO SPACE', 'danger',
      () => _send('hazard_control.emergency_vent_space', { room_id: rid }));
  }

  // Section reinforcement
  if (sec && sec.integrity < 80) {
    if (sec.reinforcing) {
      addBtn(actionsEl, 'CANCEL REINFORCEMENT', '',
        () => _send('hazard_control.cancel_reinforcement', { section_id: sec.id }));
    } else {
      addBtn(actionsEl, 'REINFORCE SECTION', '',
        () => _send('hazard_control.reinforce_section', { section_id: sec.id }));
    }
  }

  // Deck-level
  addBtn(actionsEl, `SUPPRESS DECK (${deckLabel(room.deck)})`, '',
    () => _send('hazard_control.suppress_deck', { deck_name: room.deck }));

  addBtn(actionsEl, 'EVACUATE ROOM', 'danger',
    () => _send('hazard_control.order_evacuation', { room_id: rid }));
}

function renderConnectionActions() {
  const [a, b] = _selectedConn;
  actionsTitleEl.textContent = `${roomName(a)} ↔ ${roomName(b)}`;
  actionsEl.innerHTML = '';

  const sealed = isConnectionSealed(a, b);
  const vent = getVentState(a, b);

  const detail = document.createElement('div');
  detail.className = 'hc-sel-detail';
  detail.textContent = `Sealed: ${sealed ? 'YES' : 'NO'}\nVent: ${vent || 'unknown'}`;
  actionsEl.appendChild(detail);

  // Seal / unseal emergency bulkhead connection
  if (sealed) {
    addBtn(actionsEl, 'UNSEAL CONNECTION', '',
      () => _send('hazard_control.unseal_connection', { room_a: a, room_b: b }));
  } else {
    addBtn(actionsEl, 'SEAL CONNECTION', 'danger',
      () => _send('hazard_control.seal_connection', { room_a: a, room_b: b }));
  }

  // Vent cycling
  addBtn(actionsEl, 'CYCLE VENT', '',
    () => _send('hazard_control.cycle_vent', { room_a: a, room_b: b }));

  addBtn(actionsEl, 'SET VENT: OPEN', '',
    () => _send('hazard_control.set_vent', { room_a: a, room_b: b, state: 'open' }),
    vent === 'open');

  addBtn(actionsEl, 'SET VENT: FILTERED', '',
    () => _send('hazard_control.set_vent', { room_a: a, room_b: b, state: 'filtered' }),
    vent === 'filtered');

  addBtn(actionsEl, 'SET VENT: SEALED', 'danger',
    () => _send('hazard_control.set_vent', { room_a: a, room_b: b, state: 'sealed' }),
    vent === 'sealed');
}

// ---------------------------------------------------------------------------
// Right panel: active hazard list
// ---------------------------------------------------------------------------

function renderHazardList() {
  hazardsEl.innerHTML = '';

  const entries = [];

  // Fires
  if (_dcState?.fires) {
    for (const [rid, f] of Object.entries(_dcState.fires)) {
      entries.push({ cls: 'fire', sort: 10 + f.intensity,
        html: `<div class="hc-hazard-row"><span>FIRE ${roomName(rid)}</span><span class="hc-hazard-dim">INT ${f.intensity}</span></div>` });
    }
  }

  // Breaches
  if (_atmState?.breaches) {
    for (const [rid, b] of Object.entries(_atmState.breaches)) {
      const ff = b.force_field ? ` FF ${b.force_field_timer.toFixed(0)}s` : '';
      entries.push({ cls: 'breach', sort: 9,
        html: `<div class="hc-hazard-row"><span>BREACH ${roomName(rid)}</span><span class="hc-hazard-dim">${(b.severity * 100).toFixed(0)}%${ff}</span></div>` });
    }
  }

  // Active DCTs
  if (_dcState?.active_dcts) {
    for (const [rid, prog] of Object.entries(_dcState.active_dcts)) {
      const pct = (prog * 100).toFixed(0);
      entries.push({ cls: 'dct', sort: 3, progress: prog,
        html: `<div class="hc-hazard-row"><span>DCT ${roomName(rid)}</span><span class="hc-hazard-dim">${pct}%</span></div>` });
    }
  }

  // Fire teams
  if (_dcState?.fire_teams) {
    for (const [rid, t] of Object.entries(_dcState.fire_teams)) {
      entries.push({ cls: 'fire-team', sort: 7,
        html: `<div class="hc-hazard-row"><span>FIRE TEAM ${roomName(rid)}</span><span class="hc-hazard-dim">${t.toFixed(0)}s</span></div>` });
    }
  }

  // Decon teams
  if (_atmState?.decon_teams) {
    for (const [rid, t] of Object.entries(_atmState.decon_teams)) {
      entries.push({ cls: 'decon', sort: 5,
        html: `<div class="hc-hazard-row"><span>DECON ${roomName(rid)}</span><span class="hc-hazard-dim">${t.toFixed(0)}s</span></div>` });
    }
  }

  // Sections with issues
  if (_dcState?.sections) {
    for (const [sid, sec] of Object.entries(_dcState.sections)) {
      if (sec.collapsed) {
        entries.push({ cls: 'struct', sort: 12,
          html: `<div class="hc-hazard-row"><span>COLLAPSED ${sid}</span><span class="hc-hazard-dim">0%</span></div>` });
      } else if (sec.integrity < 50) {
        entries.push({ cls: sec.reinforcing ? 'reinforce' : 'struct', sort: 6,
          html: `<div class="hc-hazard-row"><span>${sec.reinforcing ? 'REINF' : 'STRUCT'} ${sid}</span><span class="hc-hazard-dim">${sec.integrity.toFixed(0)}%</span></div>` });
      }
    }
  }

  // Deck suppression
  if (_dcState?.deck_suppression) {
    for (const [dk, t] of Object.entries(_dcState.deck_suppression)) {
      entries.push({ cls: 'fire-team', sort: 4,
        html: `<div class="hc-hazard-row"><span>DECK SUPP ${deckLabel(dk)}</span><span class="hc-hazard-dim">${t.toFixed(0)}s</span></div>` });
    }
  }

  // Space venting
  if (_atmState?.space_venting) {
    for (const rid of _atmState.space_venting) {
      entries.push({ cls: 'vent', sort: 8,
        html: `<div class="hc-hazard-row"><span>SPACE VENT ${roomName(rid)}</span></div>` });
    }
  }

  // Life pods launching
  if (_dcState?.life_pods) {
    for (const pod of _dcState.life_pods) {
      if (pod.launching && !pod.launched) {
        entries.push({ cls: 'pod', sort: 11,
          html: `<div class="hc-hazard-row"><span>POD ${pod.id}</span><span class="hc-hazard-dim">${pod.loaded_crew} crew</span></div>` });
      }
    }
  }

  entries.sort((a, b) => b.sort - a.sort);

  if (entries.length === 0) {
    hazardsEl.innerHTML = '<p class="text-dim">No active hazards.</p>';
    return;
  }

  for (const e of entries) {
    const div = document.createElement('div');
    div.className = `hc-hazard-entry hc-hazard-entry--${e.cls}`;
    div.innerHTML = e.html;
    if (e.progress != null) {
      div.innerHTML += `<div class="hc-hazard-progress"><div class="hc-hazard-progress__fill" style="width:${(e.progress * 100).toFixed(0)}%"></div></div>`;
    }
    hazardsEl.appendChild(div);
  }
}

// ---------------------------------------------------------------------------
// Event log (state-diff populated)
// ---------------------------------------------------------------------------

function addLogEntry(text, cls) {
  const now = new Date();
  const ts = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
  _eventLog.push({ text: `${ts} ${text}`, cls });
  if (_eventLog.length > MAX_LOG) _eventLog.shift();
  renderLog();
}

function renderLog() {
  logEl.innerHTML = '';
  for (let i = _eventLog.length - 1; i >= 0; i--) {
    const e = _eventLog[i];
    const div = document.createElement('div');
    div.className = `hc-log-entry${e.cls ? ' hc-log-entry--' + e.cls : ''}`;
    div.textContent = e.text;
    logEl.appendChild(div);
  }
}

// ---------------------------------------------------------------------------
// Bottom bar
// ---------------------------------------------------------------------------

function renderBottomBar() {
  // Suppressant
  const res = _shipState?.resources;
  if (res) {
    elSupp.textContent = `SUPPRESSANT ${Math.round(res.suppressant)}/${Math.round(res.suppressant_max)}`;
  }

  // Active teams count
  const dctCount = _dcState?.active_dcts ? Object.keys(_dcState.active_dcts).length : 0;
  const fireTeamCount = _dcState?.fire_teams ? Object.keys(_dcState.fire_teams).length : 0;
  const deconCount = _atmState?.decon_teams ? Object.keys(_atmState.decon_teams).length : 0;
  elTeams.textContent = `TEAMS ${dctCount + fireTeamCount + deconCount}`;

  // Force fields
  if (_atmState?.breaches) {
    const ffs = Object.values(_atmState.breaches).filter(b => b.force_field);
    const minTimer = ffs.length > 0 ? Math.min(...ffs.map(b => b.force_field_timer)) : 0;
    elFF.textContent = ffs.length > 0
      ? `FF ${ffs.length} (${minTimer.toFixed(0)}s)`
      : 'FF 0';
  }

  // Life support
  const lsEff = _shipState?.systems?.life_support?.efficiency;
  elLS.textContent = lsEff != null
    ? `LIFE SUPPORT ${(lsEff * 100).toFixed(0)}%`
    : 'LIFE SUPPORT —';
}

// ---------------------------------------------------------------------------
// State diff + audio triggers
// ---------------------------------------------------------------------------

function ensureAudio() {
  if (_audioCtx) return _audioCtx.state !== 'suspended';
  try {
    const g = SoundBank.getCategoryGain?.('events');
    if (!g) return false;
    _audioCtx = g.context;
    _audioOut = g;
    return _audioCtx.state !== 'suspended';
  } catch { return false; }
}

function playTone(freq, dur, type, vol) {
  if (!ensureAudio()) return;
  const ctx = _audioCtx;
  const now = ctx.currentTime;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = type || 'sine';
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(vol || 0.15, now);
  gain.gain.exponentialRampToValueAtTime(0.001, now + dur);
  osc.connect(gain);
  gain.connect(_audioOut);
  osc.start(now);
  osc.stop(now + dur);
}

function playNoise(dur, filterFreq, vol) {
  if (!ensureAudio()) return;
  const ctx = _audioCtx;
  const now = ctx.currentTime;
  const len = Math.floor(ctx.sampleRate * dur);
  const buf = ctx.createBuffer(1, len, ctx.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
  const src = ctx.createBufferSource();
  src.buffer = buf;
  const filter = ctx.createBiquadFilter();
  filter.type = 'bandpass';
  filter.frequency.value = filterFreq || 1000;
  filter.Q.value = 3;
  const gain = ctx.createGain();
  gain.gain.setValueAtTime(vol || 0.12, now);
  gain.gain.exponentialRampToValueAtTime(0.001, now + dur);
  src.connect(filter);
  filter.connect(gain);
  gain.connect(_audioOut);
  src.start(now);
  src.stop(now + dur);
}

// Audio cue functions
const hcAudio = {
  fireStarted()       { playNoise(0.5, 800, 0.15); playTone(200, 0.3, 'sawtooth', 0.08); },
  fireSuppressed()    { playNoise(0.4, 2000, 0.10); },
  hullBreach()        { playNoise(0.7, 400, 0.20); },
  forceFieldOn()      { playTone(440, 0.6, 'sine', 0.12); },
  forceFieldFailing() { playTone(330, 0.15, 'square', 0.10); setTimeout(() => playTone(330, 0.15, 'square', 0.10), 200); },
  radiationAlert()    { for (let i = 0; i < 6; i++) setTimeout(() => playTone(1200, 0.05, 'square', 0.08), i * 60); },
  structuralWarning() { playTone(60, 1.0, 'sine', 0.20); },
  structuralCollapse(){ playNoise(0.8, 200, 0.25); playTone(40, 0.6, 'sawtooth', 0.15); },
  deckEvacuated()     { playTone(880, 0.8, 'sine', 0.10); },
  deckUninhabitable() { playTone(220, 0.2, 'square', 0.18); setTimeout(() => playTone(220, 0.2, 'square', 0.18), 300); setTimeout(() => playTone(220, 0.2, 'square', 0.18), 600); },
};

function diffAndTriggerAudio() {
  if (!_prevDcState && !_prevAtmState) return;

  const prevFires = _prevDcState?.fires || {};
  const currFires = _dcState?.fires || {};
  const prevBreaches = _prevAtmState?.breaches || {};
  const currBreaches = _atmState?.breaches || {};
  const prevSections = _prevDcState?.sections || {};
  const currSections = _dcState?.sections || {};

  // Fire started / suppressed
  for (const rid of Object.keys(currFires)) {
    if (!prevFires[rid]) {
      hcAudio.fireStarted();
      addLogEntry(`Fire started: ${roomName(rid)} INT ${currFires[rid].intensity}`, 'fire');
    }
  }
  for (const rid of Object.keys(prevFires)) {
    if (!currFires[rid]) {
      hcAudio.fireSuppressed();
      addLogEntry(`Fire suppressed: ${roomName(rid)}`, 'good');
    }
  }

  // Hull breach
  for (const rid of Object.keys(currBreaches)) {
    if (!prevBreaches[rid]) {
      hcAudio.hullBreach();
      addLogEntry(`Hull breach: ${roomName(rid)}`, 'breach');
    }
  }

  // Force field on / failing
  for (const [rid, b] of Object.entries(currBreaches)) {
    const prev = prevBreaches[rid];
    if (b.force_field && (!prev || !prev.force_field)) {
      hcAudio.forceFieldOn();
      addLogEntry(`Force field activated: ${roomName(rid)}`, 'breach');
    }
    if (b.force_field && b.force_field_timer <= 30 && (!prev || prev.force_field_timer > 30)) {
      hcAudio.forceFieldFailing();
      addLogEntry(`Force field failing: ${roomName(rid)} ${b.force_field_timer.toFixed(0)}s`, 'breach');
    }
  }

  // Radiation zone changes
  if (_atmState?.rooms && _prevAtmState?.rooms) {
    for (const [rid, r] of Object.entries(_atmState.rooms)) {
      const prev = _prevAtmState.rooms[rid];
      if (r.rad_zone && (r.rad_zone === 'orange' || r.rad_zone === 'red') &&
          (!prev || (prev.rad_zone !== 'orange' && prev.rad_zone !== 'red'))) {
        hcAudio.radiationAlert();
        addLogEntry(`Radiation ${r.rad_zone.toUpperCase()}: ${roomName(rid)}`, 'rad');
      }
    }
  }

  // Structural: warning (<50%) and collapse
  for (const [sid, sec] of Object.entries(currSections)) {
    const prev = prevSections[sid];
    if (sec.integrity < 50 && (!prev || prev.integrity >= 50)) {
      hcAudio.structuralWarning();
      addLogEntry(`Structural warning: ${sid} ${sec.integrity.toFixed(0)}%`, 'struct');
    }
    if (sec.collapsed && (!prev || !prev.collapsed)) {
      hcAudio.structuralCollapse();
      addLogEntry(`Section collapsed: ${sid}`, 'struct');
    }
  }

  // Crew evacuation (B.2.3.3)
  const prevEvac = new Set(_prevDcState?.evacuated_rooms || []);
  const currEvac = new Set(_dcState?.evacuated_rooms || []);
  for (const rid of currEvac) {
    if (!prevEvac.has(rid)) {
      hcAudio.deckEvacuated();
      addLogEntry(`Crew evacuated: ${roomName(rid)}`, 'evac');
      break;  // one audio cue per tick
    }
  }

  // Deck-level severity changes (evacuated / uninhabitable)
  const prevDecks = _prevDeckSeverities || {};
  const currDecks = {};
  const deckStatuses = computeDeckStatuses();
  for (const d of deckStatuses) {
    currDecks[d.name] = d.metrics.severity;
    const prevSev = prevDecks[d.name] ?? 0;
    if (d.metrics.severity >= 4 && prevSev < 4) {
      hcAudio.deckUninhabitable();
      addLogEntry(`Deck UNINHABITABLE: ${deckLabel(d.name)}`, 'evac');
    }
  }
  _prevDeckSeverities = currDecks;
}

let _prevDeckSeverities = {};

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function handleGameStarted(payload) {
  standbyEl.style.display = 'none';
  hcMainEl.style.display  = 'grid';
  _gameActive = true;
  if (payload.mission_name) missionLabelEl.textContent = payload.mission_name.toUpperCase();

  if (payload.interior_layout) {
    _allRooms = payload.interior_layout;
  }

  SoundBank.setAmbient('life_support', { active: true });
  buildOverlayBar();
  resizeCanvas();
  requestAnimationFrame(animLoop);
  render();
}

function handleDcState(payload) {
  _prevDcState = _dcState;
  _dcState = payload;
  diffAndTriggerAudio();
  scheduleRender();
}

function handleAtmosphere(payload) {
  _prevAtmState = _atmState;
  _atmState = payload;
  diffAndTriggerAudio();
  scheduleRender();
}

function handleShipState(payload) {
  _shipState = payload;
  renderBottomBar();
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
    case 'hazard_control.atmosphere':
      handleAtmosphere(msg.payload);
      break;
    case 'ship.state':
      handleShipState(msg.payload);
      break;
    case 'ship.alert_changed':
      setAlertLevel(msg.payload.level);
      SoundBank.setAmbient('alert_level', { level: msg.payload.level });
      break;
    case 'ship.hull_hit':
      handleHullHit();
      break;
    case 'game.over':
      _gameActive = false;
      if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null; }
      SoundBank.play(msg.payload.result === 'victory' ? 'victory' : 'defeat');
      SoundBank.stopAmbient('life_support');
      SoundBank.stopAmbient('alert_level');
      standbyEl.style.display = 'flex';
      hcMainEl.style.display  = 'none';
      showGameOver(msg.payload.result, msg.payload.stats);
      break;
  }
}

// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------

function render() {
  guardedRenderDeckCards();
  guardedRenderActions();
  renderHazardList();
  renderBottomBar();
}

const scheduleRender = createRenderScheduler(render, 333);

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  _canvas = $('hc-canvas');
  _ctx = _canvas?.getContext('2d');

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

  // Canvas click handler
  _canvas?.addEventListener('click', handleCanvasClick);

  // Resize observer for canvas
  if (_canvas?.parentElement) {
    const ro = new ResizeObserver(() => {
      resizeCanvas();
    });
    ro.observe(_canvas.parentElement);
  }

  // Also handle window resize
  window.addEventListener('resize', resizeCanvas);
});
