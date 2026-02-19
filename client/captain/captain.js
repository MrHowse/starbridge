/**
 * Captain Station — Full Phase 6 implementation.
 *
 * Provides:
 *   - Alert level buttons → send captain.set_alert, receive ship.alert_changed
 *   - Tactical map canvas (North-up, ship at centre, enemy contacts, torpedoes)
 *   - Ship status gauges (hull, shields, power)
 *   - Science summary (active scan progress, last scan result)
 *   - Mission objectives panel (live updates via mission.objective_update)
 *   - Victory / defeat overlay
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import { setStatusDot, setAlertLevel, redirectToStation, showBriefing } from '../shared/ui_components.js';
import {
  C_PRIMARY, C_PRIMARY_DIM, C_BG, C_GRID,
  drawBackground, worldToScreen, drawShipChevron,
} from '../shared/renderer.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAP_WORLD_RADIUS = 80_000;  // half-width of tactical map in world units
const TORP_DOT_RADIUS  = 3;
const HIT_FLASH_MS     = 400;
const TRAIL_LENGTH     = 5;       // torpedo trail positions to keep

// Enemy wireframe shapes (mirrors weapons.js)
const ENEMY_SHAPES = {
  scout:     { size: 8,  color: '#ff4040' },
  cruiser:   { size: 12, color: '#ff4040' },
  destroyer: { size: 16, color: '#ff4040' },
};

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusDotEl    = document.querySelector('[data-status-dot]');
const statusLabelEl  = document.querySelector('[data-status-label]');
const standbyEl      = document.querySelector('[data-standby]');
const captainMainEl  = document.querySelector('[data-captain-main]');
const missionLabelEl = document.getElementById('mission-label');

// Alert buttons
const alertBtns = document.querySelectorAll('.alert-btn');

// Tactical map
const mapCanvas  = document.getElementById('captain-canvas');
const mapCtx     = mapCanvas ? mapCanvas.getContext('2d') : null;

// Ship status
const hullFill      = document.getElementById('hull-fill');
const hullText      = document.getElementById('hull-text');
const shieldFwdFill = document.getElementById('shield-fwd-fill');
const shieldFwdText = document.getElementById('shield-fwd-text');
const shieldAftFill = document.getElementById('shield-aft-fill');
const shieldAftText = document.getElementById('shield-aft-text');
const powerText     = document.getElementById('power-text');

// Science
const scanActiveRow      = document.getElementById('scan-active-row');
const scanEntityId       = document.getElementById('scan-entity-id');
const scanProgressFill   = document.getElementById('scan-progress-fill');
const scanResultRow      = document.getElementById('scan-result-row');
const scanResultEntity   = document.getElementById('scan-result-entity');
const scanResultWeakness = document.getElementById('scan-result-weakness');
const scienceIdle        = document.getElementById('science-idle');

// Objectives
const objectivesList = document.getElementById('objectives-list');

// Game over
const gameOverOverlay = document.getElementById('game-over-overlay');
const gameOverTitle   = document.getElementById('game-over-title');
const gameOverBody    = document.getElementById('game-over-body');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let gameActive    = false;
let currentAlert  = 'green';

/** Most recent ship.state payload */
let shipState = null;

/** Enemy and torpedo lists from world.entities */
let entities = { enemies: [], torpedoes: [] };

/** Torpedo trail ring buffers: Map<torpedoId, [{x,y}]> */
const torpedoTrails = new Map();

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();
  });

  // Re-claim role on reconnect (session restore pattern)
  const playerName = sessionStorage.getItem('player_name');
  if (playerName) {
    on('lobby.welcome', () => {
      send('lobby.claim_role', { role: 'captain', player_name: playerName });
    });
  }

  // Alert buttons
  alertBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const level = btn.dataset.alert;
      send('captain.set_alert', { level });
    });
  });

  // Server messages
  on('game.started',                handleGameStarted);
  on('ship.state',                  handleShipState);
  on('ship.alert_changed',          handleAlertChanged);
  on('world.entities',              handleWorldEntities);
  on('science.scan_progress',       handleScanProgress);
  on('science.scan_complete',       handleScanComplete);
  on('mission.objective_update',    handleObjectiveUpdate);
  on('ship.hull_hit',               handleHullHit);
  on('captain.authorization_request', handleAuthorizationRequest);
  on('weapons.authorization_result',  handleAuthorizationResult);
  on('captain.log_entry',           handleLogEntry);
  on('game.over',                   handleGameOver);

  connect();
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function handleGameStarted(payload) {
  missionLabelEl.textContent = payload.mission_name.toUpperCase();
  standbyEl.style.display     = 'none';
  captainMainEl.style.display = '';
  gameActive = true;
  resizeCanvas();
  requestAnimationFrame(renderLoop);
  _buildAuthPanel();
  _buildLogPanel();
  if (payload.briefing_text) {
    showBriefing(payload.mission_name, payload.briefing_text);
  }
}

function handleShipState(payload) {
  shipState = payload;
  if (!gameActive) return;
  updateShipStatus(payload);
}

function handleAlertChanged({ level }) {
  currentAlert = level;
  setAlertLevel(level);
  updateAlertButtons(level);
}

function handleWorldEntities(payload) {
  entities = payload;
  // Update torpedo trail ring buffers.
  const currentIds = new Set((payload.torpedoes || []).map(t => t.id));
  // Prune trails for torpedoes that no longer exist.
  for (const id of torpedoTrails.keys()) {
    if (!currentIds.has(id)) torpedoTrails.delete(id);
  }
  // Append current positions.
  for (const torp of (payload.torpedoes || [])) {
    if (!torpedoTrails.has(torp.id)) torpedoTrails.set(torp.id, []);
    const trail = torpedoTrails.get(torp.id);
    trail.push({ x: torp.x, y: torp.y });
    if (trail.length > TRAIL_LENGTH) trail.shift();
  }
}

function handleHullHit() {
  if (!gameActive) return;
  const el = document.getElementById('station-container') || document.querySelector('.station-container');
  if (el) {
    el.classList.add('hit');
    setTimeout(() => el.classList.remove('hit'), HIT_FLASH_MS);
  }
}

function handleScanProgress({ entity_id, progress }) {
  scienceIdle.style.display      = 'none';
  scanActiveRow.style.display    = '';
  scanEntityId.textContent       = entity_id;
  scanProgressFill.style.width   = `${progress}%`;
}

function handleScanComplete({ entity_id, results }) {
  scanActiveRow.style.display    = 'none';
  scanResultRow.style.display    = '';
  scanResultEntity.textContent   = `${entity_id} (${results.type || '?'})`;
  scanResultWeakness.textContent = results.weakness || 'No weakness detected.';
  scienceIdle.style.display      = 'none';
}

function handleObjectiveUpdate({ objectives }) {
  renderObjectives(objectives);
}

function handleGameOver({ result, stats = {} }) {
  gameActive = false;
  gameOverTitle.textContent = result === 'victory' ? 'MISSION COMPLETE' : 'SHIP DESTROYED';
  const dur  = stats.duration_s != null
    ? `${Math.floor(stats.duration_s / 60)}:${String(Math.round(stats.duration_s % 60)).padStart(2, '0')}`
    : '—';
  const hull = stats.hull_remaining != null ? `${Math.round(stats.hull_remaining)}%` : '—';
  gameOverBody.textContent = result === 'victory'
    ? `All objectives achieved. Duration: ${dur}. Hull: ${hull}.`
    : `Hull integrity zero. Duration: ${dur}.`;
  gameOverOverlay.style.display = '';
}

// ---------------------------------------------------------------------------
// Authorization panel
// ---------------------------------------------------------------------------

let _pendingAuthId = null;

function _buildAuthPanel() {
  const sidebar = document.querySelector('.captain-sidebar');
  if (!sidebar || document.getElementById('auth-panel')) return;

  const panel = document.createElement('section');
  panel.id        = 'auth-panel';
  panel.className = 'captain-panel panel';
  panel.style.display = 'none';
  panel.innerHTML = `
    <div class="panel__header">
      <span class="text-header" style="color:#ff4040">⚠ AUTHORIZATION REQUIRED</span>
    </div>
    <div class="captain-panel__body">
      <p class="text-body" id="auth-message">Nuclear torpedo launch requested.</p>
      <div class="auth-btns">
        <button class="btn btn--danger" id="auth-approve-btn">AUTHORIZE LAUNCH</button>
        <button class="btn btn--secondary" id="auth-deny-btn">DENY</button>
      </div>
    </div>
  `;
  sidebar.insertBefore(panel, sidebar.firstChild);

  document.getElementById('auth-approve-btn').addEventListener('click', () => {
    if (_pendingAuthId) {
      send('captain.authorize', { request_id: _pendingAuthId, approved: true });
      _hideAuthPanel();
    }
  });

  document.getElementById('auth-deny-btn').addEventListener('click', () => {
    if (_pendingAuthId) {
      send('captain.authorize', { request_id: _pendingAuthId, approved: false });
      _hideAuthPanel();
    }
  });
}

function _showAuthPanel(request_id, tube) {
  _pendingAuthId = request_id;
  const panel = document.getElementById('auth-panel');
  const msg   = document.getElementById('auth-message');
  if (!panel) return;
  if (msg) msg.textContent = `Tube ${tube} — Nuclear torpedo launch requested. Authorize?`;
  panel.style.display = '';
}

function _hideAuthPanel() {
  _pendingAuthId = null;
  const panel = document.getElementById('auth-panel');
  if (panel) panel.style.display = 'none';
}

function handleAuthorizationRequest({ request_id, action, tube }) {
  if (!gameActive) return;
  _showAuthPanel(request_id, tube);
}

function handleAuthorizationResult({ request_id, approved }) {
  if (_pendingAuthId === request_id) _hideAuthPanel();
}

// ---------------------------------------------------------------------------
// Captain's log panel
// ---------------------------------------------------------------------------

const _logEntries = [];

function _buildLogPanel() {
  const sidebar = document.querySelector('.captain-sidebar');
  if (!sidebar || document.getElementById('log-panel')) return;

  const panel = document.createElement('section');
  panel.id        = 'log-panel';
  panel.className = 'captain-panel panel';
  panel.innerHTML = `
    <div class="panel__header">
      <span class="text-header">CAPTAIN'S LOG</span>
    </div>
    <div class="captain-panel__body">
      <div class="log-entries" id="log-entries">
        <div class="text-dim">No entries.</div>
      </div>
      <div class="log-input-row">
        <input type="text" class="log-input text-data" id="log-input"
               placeholder="Record log entry…" maxlength="500">
        <button class="btn btn--secondary btn--small" id="log-add-btn">ADD</button>
      </div>
    </div>
  `;
  sidebar.appendChild(panel);

  function submitLog() {
    const input = document.getElementById('log-input');
    const text  = (input?.value || '').trim();
    if (!text || !gameActive) return;
    send('captain.add_log', { text });
    if (input) input.value = '';
  }

  document.getElementById('log-add-btn').addEventListener('click', submitLog);
  document.getElementById('log-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') submitLog();
  });
}

function handleLogEntry({ text, timestamp }) {
  _logEntries.push({ text, timestamp });
  _renderLog();
}

function _renderLog() {
  const el = document.getElementById('log-entries');
  if (!el) return;
  if (_logEntries.length === 0) {
    el.innerHTML = '<div class="text-dim">No entries.</div>';
    return;
  }
  el.innerHTML = _logEntries.map(e => {
    const d   = new Date(e.timestamp * 1000);
    const hh  = String(d.getHours()).padStart(2, '0');
    const mm  = String(d.getMinutes()).padStart(2, '0');
    return `<div class="log-entry"><span class="log-ts text-dim">${hh}:${mm}</span><span class="text-body log-text">${e.text}</span></div>`;
  }).join('');
  el.scrollTop = el.scrollHeight;
}

// ---------------------------------------------------------------------------
// Alert button UI
// ---------------------------------------------------------------------------

function updateAlertButtons(level) {
  alertBtns.forEach(btn => {
    const isActive = btn.dataset.alert === level;
    btn.classList.toggle('alert-btn--active', isActive);
  });
}

// ---------------------------------------------------------------------------
// Ship status gauges
// ---------------------------------------------------------------------------

function updateShipStatus(state) {
  const hull   = Math.max(0, Math.min(100, state.hull));
  const shields = state.shields || {};
  const fwd    = Math.max(0, Math.min(100, shields.front ?? 100));
  const aft    = Math.max(0, Math.min(100, shields.rear  ?? 100));

  if (hullFill)      hullFill.style.width      = `${hull}%`;
  if (hullText)      hullText.textContent       = Math.round(hull);
  if (shieldFwdFill) shieldFwdFill.style.width  = `${fwd}%`;
  if (shieldFwdText) shieldFwdText.textContent  = Math.round(fwd);
  if (shieldAftFill) shieldAftFill.style.width  = `${aft}%`;
  if (shieldAftText) shieldAftText.textContent  = Math.round(aft);

  // Power summary: total allocated power across all systems
  if (state.systems && powerText) {
    const total = Object.values(state.systems).reduce((s, sys) => s + (sys.power || 0), 0);
    powerText.textContent = `${Math.round(total)} / 600`;
  }
}

// ---------------------------------------------------------------------------
// Objectives rendering
// ---------------------------------------------------------------------------

function renderObjectives(objectives) {
  if (!objectivesList) return;
  if (!objectives || objectives.length === 0) {
    objectivesList.innerHTML = '<div class="text-dim">No objectives.</div>';
    return;
  }
  objectivesList.innerHTML = objectives.map(obj => {
    const cls  = obj.status === 'complete' ? 'obj-complete' : 'obj-pending';
    const icon = obj.status === 'complete' ? '✓' : '○';
    return `
      <div class="objective-row ${cls}">
        <span class="obj-icon text-data">${icon}</span>
        <span class="obj-text text-body">${obj.text}</span>
      </div>`;
  }).join('');
}

// ---------------------------------------------------------------------------
// Tactical map rendering
// ---------------------------------------------------------------------------

function resizeCanvas() {
  if (!mapCanvas) return;
  const rect = mapCanvas.getBoundingClientRect();
  mapCanvas.width  = rect.width  || mapCanvas.offsetWidth;
  mapCanvas.height = rect.height || mapCanvas.offsetHeight;
}

function renderLoop() {
  if (!gameActive) return;
  drawTacticalMap();
  requestAnimationFrame(renderLoop);
}

function drawTacticalMap() {
  if (!mapCtx || !mapCanvas) return;

  const cw = mapCanvas.width;
  const ch = mapCanvas.height;

  // Keep canvas sized to element
  if (cw !== mapCanvas.offsetWidth || ch !== mapCanvas.offsetHeight) {
    resizeCanvas();
  }

  drawBackground(mapCtx, cw, ch);

  if (!shipState) return;

  const camX = shipState.position?.x ?? 50_000;
  const camY = shipState.position?.y ?? 50_000;
  const zoom = MAP_WORLD_RADIUS / (Math.min(cw, ch) / 2);

  // Grid lines (faint 20k grid)
  drawGrid(mapCtx, cw, ch, camX, camY, zoom);

  // Enemy contacts
  for (const enemy of (entities.enemies || [])) {
    drawEnemy(mapCtx, enemy, camX, camY, zoom, cw, ch);
  }

  // Torpedo dots with trails
  for (const torp of (entities.torpedoes || [])) {
    const trail = torpedoTrails.get(torp.id) || [];
    // Draw trail (older = dimmer).
    for (let i = 0; i < trail.length - 1; i++) {
      const alpha = (i + 1) / trail.length * 0.5;
      const sp = worldToScreen(trail[i].x, trail[i].y, camX, camY, zoom, cw, ch);
      mapCtx.fillStyle = `rgba(0, 255, 65, ${alpha})`;
      mapCtx.beginPath();
      mapCtx.arc(sp.x, sp.y, 2, 0, Math.PI * 2);
      mapCtx.fill();
    }
    // Draw bright head.
    const sp = worldToScreen(torp.x, torp.y, camX, camY, zoom, cw, ch);
    mapCtx.beginPath();
    mapCtx.arc(sp.x, sp.y, TORP_DOT_RADIUS, 0, Math.PI * 2);
    mapCtx.fillStyle = C_PRIMARY;
    mapCtx.fill();
  }

  // Ship chevron at centre
  const heading = shipState.heading ?? 0;
  const headRad = heading * Math.PI / 180;
  drawShipChevron(mapCtx, cw / 2, ch / 2, headRad, 8, C_PRIMARY);

  // Heading label
  mapCtx.fillStyle    = C_PRIMARY_DIM;
  mapCtx.font         = '10px "Share Tech Mono", monospace';
  mapCtx.textAlign    = 'center';
  mapCtx.textBaseline = 'top';
  const hdgStr = Math.round(heading).toString().padStart(3, '0');
  mapCtx.fillText(`HDG ${hdgStr}°`, cw / 2, ch / 2 + 14);
}

function drawGrid(ctx, cw, ch, camX, camY, zoom) {
  const GRID_SPACING = 20_000;
  ctx.strokeStyle = C_GRID;
  ctx.lineWidth   = 0.5;

  // Vertical lines
  const xStart = Math.floor((camX - MAP_WORLD_RADIUS) / GRID_SPACING) * GRID_SPACING;
  const xEnd   = camX + MAP_WORLD_RADIUS;
  for (let wx = xStart; wx <= xEnd; wx += GRID_SPACING) {
    const sp = worldToScreen(wx, camY, camX, camY, zoom, cw, ch);
    ctx.beginPath();
    ctx.moveTo(sp.x, 0);
    ctx.lineTo(sp.x, ch);
    ctx.stroke();
  }

  // Horizontal lines
  const yStart = Math.floor((camY - MAP_WORLD_RADIUS) / GRID_SPACING) * GRID_SPACING;
  const yEnd   = camY + MAP_WORLD_RADIUS;
  for (let wy = yStart; wy <= yEnd; wy += GRID_SPACING) {
    const sp = worldToScreen(camX, wy, camX, camY, zoom, cw, ch);
    ctx.beginPath();
    ctx.moveTo(0, sp.y);
    ctx.lineTo(cw, sp.y);
    ctx.stroke();
  }
}

function drawEnemy(ctx, enemy, camX, camY, zoom, cw, ch) {
  const sp = worldToScreen(enemy.x, enemy.y, camX, camY, zoom, cw, ch);
  const shape = ENEMY_SHAPES[enemy.type] || ENEMY_SHAPES.scout;

  ctx.save();
  ctx.translate(sp.x, sp.y);

  const headRad = (enemy.heading || 0) * Math.PI / 180;
  ctx.rotate(headRad);

  ctx.strokeStyle = shape.color;
  ctx.lineWidth   = 1.5;

  const s = shape.size;
  if (enemy.type === 'scout') {
    // Diamond
    ctx.beginPath();
    ctx.moveTo(0, -s);
    ctx.lineTo(s, 0);
    ctx.lineTo(0, s);
    ctx.lineTo(-s, 0);
    ctx.closePath();
    ctx.stroke();
  } else if (enemy.type === 'cruiser') {
    // Triangle
    ctx.beginPath();
    ctx.moveTo(0, -s);
    ctx.lineTo(s, s);
    ctx.lineTo(-s, s);
    ctx.closePath();
    ctx.stroke();
  } else {
    // Hexagon for destroyer / unknown
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = (i * Math.PI) / 3 - Math.PI / 6;
      const px = Math.cos(a) * s;
      const py = Math.sin(a) * s;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.closePath();
    ctx.stroke();
  }

  ctx.restore();

  // Entity ID label
  ctx.fillStyle    = 'rgba(255, 64, 64, 0.6)';
  ctx.font         = '9px "Share Tech Mono", monospace';
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'top';
  ctx.fillText(enemy.id, sp.x, sp.y + s + 2);
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

window.addEventListener('resize', () => {
  if (gameActive) resizeCanvas();
});

document.addEventListener('DOMContentLoaded', init);
