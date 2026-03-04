/**
 * Flight Operations Station — v0.06.5
 *
 * Tactical map with drone positions, waypoints, mission routes, sensor coverage.
 * Drone status cards with fuel/hull/ammo bars, callsigns, action buttons.
 * Hangar section with turnaround progress.
 * Keyboard shortcuts for rapid operations.
 */

import { initSharedUI, on, send } from '../shared/station_base.js';
import { initRoleBar } from '../shared/role_bar.js';
import { initCrewRoster } from '../shared/crew_roster.js';
import { SoundBank } from '../shared/audio.js';
import '../shared/audio_ambient.js';
import '../shared/audio_events.js';
import { wireButtonSounds } from '../shared/audio_ui.js';
import { RangeControl, STATION_RANGES } from '../shared/range_control.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

let _mapWorldRadius = 60_000;
let _foRangeControl = null;

const FUEL_LOW = 25.0;
const HULL_LOW = 50.0;

// Drone type → map colour.
const TYPE_COLOURS = {
  scout:     '#ffcc00',
  combat:    '#ff4040',
  rescue:    '#00cc66',
  survey:    '#4fc3f7',
  ecm_drone: '#cc66ff',
};

// Statuses that appear on the map (i.e. drone is "in the air").
const AIRBORNE_STATUSES = new Set([
  'launching', 'active', 'rtb', 'recovering', 'emergency',
]);

// Statuses that appear in hangar section.
const HANGAR_STATUSES = new Set([
  'hangar', 'maintenance', 'refuelling', 'rearming',
]);

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const standbyEl     = document.querySelector('[data-standby]');
const mainEl        = document.querySelector('[data-fo-main]');
const statusBarWrap = document.querySelector('[data-fo-status]');
const missionLabel  = document.getElementById('mission-label');

const mapCanvas   = document.getElementById('fo-map');
const mapPanelEl  = document.getElementById('fo-map-panel');
const canvasWrap  = document.getElementById('fo-canvas-wrap');
const mapCoordEl  = document.getElementById('fo-map-coord');
const targetHint  = document.getElementById('fo-target-hint');
const modeIndEl   = document.getElementById('fo-mode-indicator');

const droneCardsEl = document.getElementById('fo-drone-cards');
const hangarCardsEl = document.getElementById('fo-hangar-cards');
const decoyStockEl = document.getElementById('fo-decoy-stock');
const buoyListEl   = document.getElementById('fo-buoy-list');
const deployDecoyBtn = document.getElementById('fo-deploy-decoy-btn');
const statusBarEl  = document.getElementById('fo-status-bar');

const ctx = mapCanvas.getContext('2d');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let shipState = null;
let foState   = null;
let _carrierState = null;

// Sensor contacts from ship.state for drawing on tactical map.
let _sensorContacts = [];

// Currently selected drone id.
let _selectedDroneId = null;

// Camera override: when set, map centres on this position instead of ship.
let _cameraOverride = null; // { x, y } or null
let _droneCentredView = false; // Space toggle: follow selected drone

// Interaction mode:
//   null                          — idle
//   { type: 'waypoint' }          — click map to set waypoint
//   { type: 'patrol', points: [] }— ctrl+click to add patrol waypoints
//   { type: 'target' }            — click contact to designate target
//   { type: 'decoy' }             — click map to set decoy direction
let _interactionMode = null;

// Hash guards — skip DOM rebuild when only bar values changed.
let _prevDroneStructKey = '';
let _prevHangarStructKey = '';

// ---------------------------------------------------------------------------
// Shared UI init
// ---------------------------------------------------------------------------

SoundBank.init();
wireButtonSounds(SoundBank);
initRoleBar(send, 'flight_ops');
initCrewRoster(send);

initSharedUI({
  role: 'flight_ops',
  onConnect() {},
  onDisconnect() {},
  onGameStarted(payload) {
    standbyEl.style.display = 'none';
    mainEl.style.display    = 'grid';
    statusBarWrap.style.display = '';
    if (payload.mission_name) missionLabel.textContent = payload.mission_name;

    const rangeBarEl = document.getElementById('range-bar');
    if (rangeBarEl && !_foRangeControl) {
      const cfg = STATION_RANGES.flight_ops;
      _foRangeControl = new RangeControl({
        container:    rangeBarEl,
        stationId:    'flight_ops',
        ranges:       cfg.available,
        defaultRange: cfg.default,
        onChange: (_key, worldUnits) => {
          _mapWorldRadius = worldUnits;
          renderMap();
        },
      });
      _foRangeControl.attach();
      _mapWorldRadius = _foRangeControl.currentRangeUnits();
    }

    resizeCanvas();
    SoundBank.setAmbient('life_support', { active: true });

    // Ship-class-specific panels
    const squadronPanel = document.getElementById('squadron-panel');
    if (squadronPanel) squadronPanel.style.display = (payload.ship_class === 'carrier') ? '' : 'none';
  },
  onGameOver(payload) {
    standbyEl.style.display = '';
    mainEl.style.display    = 'none';
    statusBarWrap.style.display = 'none';
    missionLabel.textContent = 'MISSION ENDED';
    foState = null;
    shipState = null;
    _prevDroneStructKey = '';
    _prevHangarStructKey = '';
    SoundBank.play((payload && payload.result === 'victory') ? 'victory' : 'defeat');
    SoundBank.stopAmbient('life_support');
    SoundBank.stopAmbient('alert_level');
  },
});

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

on('ship.state', payload => {
  shipState = payload;
  renderMap();
});

on('sensor.contacts', payload => {
  _sensorContacts = payload.contacts || [];
  renderMap();
});

on('ship.alert_changed', ({ level }) => {
  SoundBank.setAmbient('alert_level', { level });
});

on('ship.hull_hit', () => {
  SoundBank.play('hull_hit');
});

on('flight_ops.state', payload => {
  foState = payload;
  renderDroneCards();
  renderHangarCards();
  renderExpendables();
  renderStatusBar();
  renderMap();
});

on('carrier.state', payload => {
  _carrierState = payload;
  renderCarrierPanel();
});

on('flight_ops.events', ({ events }) => {
  if (!events) return;
  for (const ev of events) {
    switch (ev.type) {
      case 'drone_launched':
        SoundBank.play('drone_launch');          // catapult whoosh
        break;
      case 'drone_recovered':
        SoundBank.play('drone_recovery');         // descending tone
        break;
      case 'drone_destroyed':
        SoundBank.play('drone_destroyed');         // explosion + static
        break;
      case 'drone_lost':
        SoundBank.play('drone_lost');              // solemn descending
        break;
      case 'bingo_fuel':
        SoundBank.play('bingo_fuel');              // pulsing fuel alarm
        break;
      case 'launch_failure':
        SoundBank.play('warning');
        break;
      case 'bolter':
        SoundBank.play('bolter');                  // buzzer
        break;
      case 'drone_crash_on_deck':
        SoundBank.play('warning');
        break;
      case 'contact_detected':
        SoundBank.play('contact_ping');            // proximity ping
        break;
      case 'target_destroyed':
        SoundBank.play('torpedo_hit');             // confirmed kill
        break;
      case 'survivor_pickup':
        SoundBank.play('survivor_pickup');          // positive chime
        break;
      case 'decoy_deployed':
        SoundBank.play('decoy_deploy');            // electronic burst
        break;
      case 'buoy_deployed':
        SoundBank.play('buoy_deploy');             // sonar ping
        break;
    }
  }
});

// ---------------------------------------------------------------------------
// Canvas resize
// ---------------------------------------------------------------------------

function resizeCanvas() {
  const rect = canvasWrap.getBoundingClientRect();
  mapCanvas.width  = rect.width;
  mapCanvas.height = rect.height;
  renderMap();
}

window.addEventListener('resize', resizeCanvas);

// ---------------------------------------------------------------------------
// Coordinate conversion
// ---------------------------------------------------------------------------

function _getCamPos() {
  if (!shipState) return { x: 0, y: 0 };
  // Drone-centred view: follow selected drone if airborne.
  if (_droneCentredView && _selectedDroneId && foState) {
    const d = foState.drones.find(d => d.id === _selectedDroneId);
    if (d && AIRBORNE_STATUSES.has(d.status)) return { x: d.x, y: d.y };
  }
  if (_cameraOverride) return _cameraOverride;
  return shipState.position;
}

function worldToCanvas(wx, wy) {
  if (!shipState) return { cx: 0, cy: 0 };
  const cam = _getCamPos();
  const w = mapCanvas.width;
  const h = mapCanvas.height;
  const scale = Math.min(w, h) / 2 / _mapWorldRadius;
  return {
    cx: w / 2 + (wx - cam.x) * scale,
    cy: h / 2 + (wy - cam.y) * scale,
  };
}

function canvasToWorld(px, py) {
  if (!shipState) return { wx: 0, wy: 0 };
  const cam = _getCamPos();
  const w = mapCanvas.width;
  const h = mapCanvas.height;
  const scale = Math.min(w, h) / 2 / _mapWorldRadius;
  return {
    wx: cam.x + (px - w / 2) / scale,
    wy: cam.y + (py - h / 2) / scale,
  };
}

function worldScale() {
  return Math.min(mapCanvas.width, mapCanvas.height) / 2 / _mapWorldRadius;
}

// ---------------------------------------------------------------------------
// Map rendering
// ---------------------------------------------------------------------------

function renderMap() {
  const w = mapCanvas.width;
  const h = mapCanvas.height;
  if (!w || !h) return;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#060e06';
  ctx.fillRect(0, 0, w, h);

  if (!foState || !shipState) return;

  drawGrid();
  drawSensorCoverage();
  drawContacts();
  drawDecoys();
  drawBuoys();
  drawDroneRoutes();
  drawDrones();
  drawRecoveryOrbit();
  const shipScreen = worldToCanvas(shipState.position.x, shipState.position.y);
  drawShip(shipScreen.cx, shipScreen.cy, shipState.heading);
  drawPatrolPreview();
  drawTargetingReticle(w, h);
}

function drawGrid() {
  const w = mapCanvas.width;
  const h = mapCanvas.height;
  const scale = worldScale();
  const cx = w / 2;
  const cy = h / 2;

  ctx.strokeStyle = 'rgba(0,255,65,0.04)';
  ctx.lineWidth = 1;

  for (const ring of [10_000, 20_000, 40_000, 80_000]) {
    const r = ring * scale;
    if (r < 5) continue;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
  }
}

const CONTACT_COLOURS = {
  hostile: '#ff4040',
  unknown: '#ffffff',
  friendly: '#00ff41',
  neutral: '#ffaa00',
};
const C_FO_CREATURE = '#ff44ff';
const C_FO_ANOMALY  = '#00ddff';

function drawContacts() {
  if (!_sensorContacts || _sensorContacts.length === 0) return;

  for (const c of _sensorContacts) {
    const { cx, cy } = worldToCanvas(c.x, c.y);
    const colour = CONTACT_COLOURS[c.classification] || CONTACT_COLOURS.unknown;
    const kind = c.kind || 'enemy';

    // Draw contact icon based on kind.
    ctx.save();
    ctx.translate(cx, cy);
    ctx.strokeStyle = colour;
    ctx.fillStyle = colour;
    ctx.lineWidth = 1;

    if (kind === 'station') {
      // Square with crosshair.
      ctx.strokeRect(-5, -5, 10, 10);
      ctx.beginPath();
      ctx.moveTo(-3, 0); ctx.lineTo(3, 0);
      ctx.moveTo(0, -3); ctx.lineTo(0, 3);
      ctx.stroke();
    } else if (kind === 'creature') {
      // Organic 3-lobed trefoil in magenta.
      ctx.strokeStyle = C_FO_CREATURE;
      ctx.fillStyle   = C_FO_CREATURE;
      const cr = 6;
      ctx.beginPath();
      for (let i = 0; i < 3; i++) {
        const a = (i * Math.PI * 2) / 3 - Math.PI / 2;
        const lx = Math.cos(a) * cr * 0.45;
        const ly = Math.sin(a) * cr * 0.45;
        ctx.moveTo(lx + cr * 0.55, ly);
        ctx.arc(lx, ly, cr * 0.55, 0, Math.PI * 2);
      }
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(0, 0, 1.5, 0, Math.PI * 2);
      ctx.fill();
    } else if (kind === 'wreck') {
      // Pulsing diamond with ? in cyan.
      ctx.strokeStyle = C_FO_ANOMALY;
      ctx.fillStyle   = C_FO_ANOMALY;
      const ws = 6;
      ctx.globalAlpha = 0.6 + 0.4 * Math.sin(Date.now() * 0.004);
      ctx.beginPath();
      ctx.moveTo(0, -ws); ctx.lineTo(ws, 0);
      ctx.lineTo(0, ws);  ctx.lineTo(-ws, 0);
      ctx.closePath();
      ctx.stroke();
      ctx.font = 'bold 11px monospace';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('?', 0, 0);
    } else if (c.scan_state === 'scanned') {
      // Scanned enemy — solid triangle.
      ctx.beginPath();
      ctx.moveTo(0, -5);
      ctx.lineTo(5, 4);
      ctx.lineTo(-5, 4);
      ctx.closePath();
      ctx.stroke();
    } else {
      // Unscanned enemy — pulsing circle.
      ctx.globalAlpha = 0.5 + 0.2 * Math.sin(Date.now() * 0.004);
      ctx.beginPath();
      ctx.arc(0, 0, 4, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();

    // Contact label — type-aware.
    let labelColor = colour;
    let label;
    if (kind === 'creature') {
      labelColor = C_FO_CREATURE;
      const ctype = (c.creature_type || '').replace(/_/g, ' ').toUpperCase();
      label = ctype ? `CREATURE: ${ctype}` : c.id;
    } else if (kind === 'wreck') {
      labelColor = C_FO_ANOMALY;
      const wtype = (c.enemy_type || '').replace(/_/g, ' ').toUpperCase();
      label = wtype ? `WRECK: ${wtype}` : c.id;
    } else {
      label = c.name || (c.scan_state === 'scanned' ? c.id : 'CONTACT');
    }
    ctx.fillStyle = labelColor;
    ctx.font = '11px monospace';
    if (label) ctx.fillText(label, cx + 7, cy + 3);
  }
}

function drawSensorCoverage() {
  const scale = worldScale();

  // Drone sensor bubbles — all airborne drones with sensor capability.
  for (const d of foState.drones) {
    if (!AIRBORNE_STATUSES.has(d.status)) continue;
    const sensorRange = d.sensor_range || 0;
    if (sensorRange <= 0) continue;
    const colour = TYPE_COLOURS[d.drone_type] || '#888';
    const range = sensorRange * scale;
    if (range < 2) continue;
    const { cx, cy } = worldToCanvas(d.x, d.y);
    ctx.save();
    ctx.globalAlpha = 0.06;
    ctx.fillStyle = colour;
    ctx.beginPath();
    ctx.arc(cx, cy, range, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 0.3;
    ctx.strokeStyle = colour;
    ctx.lineWidth = 0.5;
    ctx.stroke();
    ctx.restore();
  }

  // Buoy coverage (15000 world units).
  for (const b of foState.buoys) {
    if (!b.active) continue;
    const range = 15_000 * scale;
    if (range < 2) continue;
    const { cx, cy } = worldToCanvas(b.x, b.y);
    ctx.save();
    ctx.globalAlpha = 0.06;
    ctx.fillStyle = '#ffb000';
    ctx.beginPath();
    ctx.arc(cx, cy, range, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 0.3;
    ctx.strokeStyle = '#ffb000';
    ctx.lineWidth = 0.5;
    ctx.stroke();
    ctx.restore();
  }
}

function drawDecoys() {
  for (const d of foState.decoys) {
    const { cx, cy } = worldToCanvas(d.x, d.y);
    // Flashing diamond.
    const alpha = 0.4 + 0.6 * Math.abs(Math.sin(Date.now() / 200));
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.fillStyle = '#ff8800';
    ctx.beginPath();
    ctx.moveTo(cx, cy - 4);
    ctx.lineTo(cx + 3, cy);
    ctx.lineTo(cx, cy + 4);
    ctx.lineTo(cx - 3, cy);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
    // Timer label.
    ctx.fillStyle = '#ff8800';
    ctx.font = '11px monospace';
    ctx.fillText(`${Math.round(d.lifetime)}s`, cx + 5, cy + 3);
  }
}

function drawBuoys() {
  for (const b of foState.buoys) {
    if (!b.active) continue;
    const { cx, cy } = worldToCanvas(b.x, b.y);
    drawDiamond(cx, cy, 4, '#ffb000');
    ctx.fillStyle = '#ffb000';
    ctx.font = '11px monospace';
    ctx.fillText('BUOY', cx + 6, cy + 3);
  }
}

function drawDroneRoutes() {
  // Draw waypoint routes for selected drone.
  if (!_selectedDroneId) return;
  const drone = foState.drones.find(d => d.id === _selectedDroneId);
  if (!drone || !AIRBORNE_STATUSES.has(drone.status)) return;
  const colour = TYPE_COLOURS[drone.drone_type] || '#888';

  // Draw waypoint route.
  const wps = drone.waypoints || [];
  if (wps.length > 0) {
    ctx.strokeStyle = colour;
    ctx.lineWidth = 1;
    ctx.globalAlpha = 0.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();

    // Line from drone to first remaining waypoint.
    const startIdx = drone.waypoint_index || 0;
    const { cx: dx, cy: dy } = worldToCanvas(drone.x, drone.y);
    ctx.moveTo(dx, dy);

    for (let i = startIdx; i < wps.length; i++) {
      const { cx, cy } = worldToCanvas(wps[i][0], wps[i][1]);
      ctx.lineTo(cx, cy);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1.0;

    // Draw waypoint markers.
    for (let i = 0; i < wps.length; i++) {
      const { cx, cy } = worldToCanvas(wps[i][0], wps[i][1]);
      const done = i < startIdx;
      ctx.beginPath();
      ctx.arc(cx, cy, done ? 2 : 3, 0, Math.PI * 2);
      ctx.fillStyle = done ? 'rgba(255,255,255,0.2)' : colour;
      ctx.fill();
      if (!done) {
        ctx.fillStyle = colour;
        ctx.font = '11px monospace';
        ctx.fillText(`${i + 1}`, cx + 5, cy - 2);
      }
    }
  }

  // Draw line to loiter point if present.
  if (drone.loiter_point && wps.length === 0) {
    const { cx: dx, cy: dy } = worldToCanvas(drone.x, drone.y);
    const { cx: lx, cy: ly } = worldToCanvas(drone.loiter_point[0], drone.loiter_point[1]);
    ctx.strokeStyle = colour;
    ctx.lineWidth = 1;
    ctx.globalAlpha = 0.4;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(dx, dy);
    ctx.lineTo(lx, ly);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1.0;
    drawDiamond(lx, ly, 3, colour);
  }
}

function drawDrones() {
  for (const d of foState.drones) {
    if (!AIRBORNE_STATUSES.has(d.status)) continue;
    const { cx, cy } = worldToCanvas(d.x, d.y);
    const colour = TYPE_COLOURS[d.drone_type] || '#888';
    const selected = d.id === _selectedDroneId;

    // Selection ring.
    if (selected) {
      ctx.strokeStyle = 'rgba(0,255,65,0.5)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(cx, cy, 10, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Draw type-specific icon.
    ctx.save();
    ctx.translate(cx, cy);
    drawDroneIcon(d.drone_type, colour);
    ctx.restore();

    // Callsign label.
    ctx.fillStyle = selected ? '#fff' : colour;
    ctx.font = selected ? 'bold 11px monospace' : '10px monospace';
    ctx.fillText(d.callsign || d.id, cx + 8, cy - 3);

    // Status indicator for RTB drones.
    if (d.ai_behaviour === 'rtb') {
      ctx.fillStyle = 'rgba(255,176,0,0.7)';
      ctx.font = '11px monospace';
      ctx.fillText('RTB', cx + 8, cy + 8);
    }
  }
}

function drawDroneIcon(droneType, colour) {
  ctx.fillStyle = colour;
  ctx.strokeStyle = colour;
  ctx.lineWidth = 1;

  switch (droneType) {
    case 'scout':
      // Diamond ◇
      ctx.beginPath();
      ctx.moveTo(0, -5);
      ctx.lineTo(4, 0);
      ctx.lineTo(0, 5);
      ctx.lineTo(-4, 0);
      ctx.closePath();
      ctx.fill();
      break;
    case 'combat':
      // Inverted triangle ▽
      ctx.beginPath();
      ctx.moveTo(-5, -3);
      ctx.lineTo(5, -3);
      ctx.lineTo(0, 5);
      ctx.closePath();
      ctx.fill();
      break;
    case 'rescue':
      // Plus/cross +
      ctx.fillRect(-1, -5, 2, 10);
      ctx.fillRect(-5, -1, 10, 2);
      break;
    case 'survey':
      // Square □
      ctx.strokeRect(-4, -4, 8, 8);
      break;
    case 'ecm_drone':
      // Diamond with dot ◈
      ctx.beginPath();
      ctx.moveTo(0, -5);
      ctx.lineTo(4, 0);
      ctx.lineTo(0, 5);
      ctx.lineTo(-4, 0);
      ctx.closePath();
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(0, 0, 1.5, 0, Math.PI * 2);
      ctx.fill();
      break;
    default:
      ctx.beginPath();
      ctx.arc(0, 0, 3, 0, Math.PI * 2);
      ctx.fill();
  }
}

function drawShip(cx, cy, heading) {
  const angleRad = ((heading - 90) * Math.PI) / 180;
  const size = 8;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(angleRad);
  ctx.beginPath();
  ctx.moveTo(0, -size);
  ctx.lineTo(size * 0.6, size * 0.8);
  ctx.lineTo(0, size * 0.4);
  ctx.lineTo(-size * 0.6, size * 0.8);
  ctx.closePath();
  ctx.fillStyle = '#00ff41';
  ctx.fill();
  ctx.restore();
}

function drawRecoveryOrbit() {
  if (!foState || !shipState) return;
  const rtbDrones = foState.drones.filter(d => d.status === 'rtb' || d.status === 'recovering');
  if (rtbDrones.length === 0) return;
  const shipPos = worldToCanvas(shipState.position.x, shipState.position.y);
  const orbitR = 3000 * worldScale();
  if (orbitR < 3) return;
  ctx.save();
  ctx.strokeStyle = 'rgba(255,176,0,0.25)';
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 6]);
  ctx.beginPath();
  ctx.arc(shipPos.cx, shipPos.cy, orbitR, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();
}

function drawPatrolPreview() {
  if (!_interactionMode || _interactionMode.type !== 'patrol') return;
  const pts = _interactionMode.points;
  if (pts.length < 1) return;

  ctx.strokeStyle = 'rgba(0,255,65,0.5)';
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  for (let i = 0; i < pts.length; i++) {
    const { cx, cy } = worldToCanvas(pts[i][0], pts[i][1]);
    if (i === 0) ctx.moveTo(cx, cy);
    else ctx.lineTo(cx, cy);
  }
  ctx.stroke();
  ctx.setLineDash([]);

  // Draw waypoint markers.
  for (let i = 0; i < pts.length; i++) {
    const { cx, cy } = worldToCanvas(pts[i][0], pts[i][1]);
    ctx.fillStyle = '#00ff41';
    ctx.beginPath();
    ctx.arc(cx, cy, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = 'rgba(0,255,65,0.7)';
    ctx.font = '11px monospace';
    ctx.fillText(`${i + 1}`, cx + 5, cy - 2);
  }
}

function drawTargetingReticle(w, h) {
  if (!_interactionMode) return;
  ctx.strokeStyle = 'rgba(0,255,65,0.3)';
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  ctx.strokeRect(0, 0, w, h);
  ctx.setLineDash([]);
}

function drawDiamond(cx, cy, r, colour) {
  ctx.beginPath();
  ctx.moveTo(cx, cy - r);
  ctx.lineTo(cx + r, cy);
  ctx.lineTo(cx, cy + r);
  ctx.lineTo(cx - r, cy);
  ctx.closePath();
  ctx.fillStyle = colour;
  ctx.fill();
}

// ---------------------------------------------------------------------------
// Map mouse interactions
// ---------------------------------------------------------------------------

canvasWrap.addEventListener('click', e => {
  const rect = canvasWrap.getBoundingClientRect();
  const px = e.clientX - rect.left;
  const py = e.clientY - rect.top;
  const { wx, wy } = canvasToWorld(px, py);

  if (_interactionMode) {
    if (_interactionMode.type === 'waypoint' && _selectedDroneId) {
      send('flight_ops.set_waypoint', {
        drone_id: _selectedDroneId,
        x: Math.round(wx),
        y: Math.round(wy),
      });
      SoundBank.play('scan_complete');
      exitInteractionMode();
      return;
    }
    if (_interactionMode.type === 'patrol') {
      _interactionMode.points.push([Math.round(wx), Math.round(wy)]);
      SoundBank.play('scan_complete');
      renderMap();
      return;
    }
    if (_interactionMode.type === 'decoy' && shipState) {
      const dx = wx - shipState.position.x;
      const dy = wy - shipState.position.y;
      const direction = ((Math.atan2(dx, -dy) * 180 / Math.PI) + 360) % 360;
      send('flight_ops.deploy_decoy', { direction: Math.round(direction) });
      SoundBank.play('torpedo_launch');
      exitInteractionMode();
      return;
    }
    if (_interactionMode.type === 'target' && _selectedDroneId) {
      // Find nearest contact to click.
      let bestDist = 20;
      let bestId = null;
      for (const c of _sensorContacts) {
        const { cx, cy } = worldToCanvas(c.x, c.y);
        const dist = Math.hypot(px - cx, py - cy);
        if (dist < bestDist) {
          bestDist = dist;
          bestId = c.id;
        }
      }
      if (bestId) {
        send('flight_ops.designate_target', { drone_id: _selectedDroneId, target_id: bestId });
        SoundBank.play('scan_complete');
      }
      exitInteractionMode();
      return;
    }
    return;
  }

  // Shift+click — set loiter point for selected drone.
  if (e.shiftKey && _selectedDroneId && foState) {
    const drone = foState.drones.find(d => d.id === _selectedDroneId);
    if (drone && drone.status === 'active') {
      send('flight_ops.set_loiter_point', {
        drone_id: _selectedDroneId,
        x: Math.round(wx),
        y: Math.round(wy),
      });
      SoundBank.play('scan_complete');
      return;
    }
  }

  // No mode active — check if clicking a drone icon.
  if (foState) {
    for (const d of foState.drones) {
      if (!AIRBORNE_STATUSES.has(d.status)) continue;
      const { cx, cy } = worldToCanvas(d.x, d.y);
      const dist = Math.hypot(px - cx, py - cy);
      if (dist < 12) {
        selectDrone(d.id);
        return;
      }
    }
  }

  // Click on empty space with drone selected — set waypoint.
  if (_selectedDroneId && foState) {
    const drone = foState.drones.find(d => d.id === _selectedDroneId);
    if (drone && drone.status === 'active') {
      send('flight_ops.set_waypoint', {
        drone_id: _selectedDroneId,
        x: Math.round(wx),
        y: Math.round(wy),
      });
      SoundBank.play('scan_complete');
    }
  }
});

canvasWrap.addEventListener('mousemove', e => {
  if (!shipState) return;
  const rect = canvasWrap.getBoundingClientRect();
  const px = e.clientX - rect.left;
  const py = e.clientY - rect.top;
  const { wx, wy } = canvasToWorld(px, py);
  mapCoordEl.textContent = `${Math.round(wx)}, ${Math.round(wy)}`;
});

canvasWrap.addEventListener('mouseleave', () => {
  mapCoordEl.textContent = '';
});

// Right-click context menu.
canvasWrap.addEventListener('contextmenu', e => {
  e.preventDefault();
  if (!foState || !shipState) return;

  // Remove any existing context menu.
  const existing = document.getElementById('fo-ctx-menu');
  if (existing) existing.remove();

  const rect = canvasWrap.getBoundingClientRect();
  const px = e.clientX - rect.left;
  const py = e.clientY - rect.top;
  const { wx, wy } = canvasToWorld(px, py);
  const worldX = Math.round(wx);
  const worldY = Math.round(wy);

  const menu = document.createElement('div');
  menu.id = 'fo-ctx-menu';
  menu.className = 'fo-ctx-menu';
  menu.style.left = `${px}px`;
  menu.style.top = `${py}px`;

  const items = [];

  if (_selectedDroneId) {
    const drone = foState.drones.find(d => d.id === _selectedDroneId);
    if (drone && drone.status === 'active') {
      items.push({ label: 'Set Waypoint', action: () => {
        send('flight_ops.set_waypoint', { drone_id: _selectedDroneId, x: worldX, y: worldY });
      }});
      items.push({ label: 'Set Loiter', action: () => {
        send('flight_ops.set_loiter_point', { drone_id: _selectedDroneId, x: worldX, y: worldY });
      }});
      if (drone.drone_type === 'combat' || drone.drone_type === 'scout') {
        items.push({ label: 'Designate Target', action: () => enterTargetMode() });
      }
      if (drone.drone_type === 'survey') {
        items.push({ label: 'Deploy Buoy', action: () => {
          send('flight_ops.deploy_buoy', { drone_id: _selectedDroneId });
        }});
      }
    }
  }
  items.push({ label: 'Deploy Decoy', action: () => {
    const dx = wx - shipState.position.x;
    const dy = wy - shipState.position.y;
    const direction = ((Math.atan2(dx, -dy) * 180 / Math.PI) + 360) % 360;
    send('flight_ops.deploy_decoy', { direction: Math.round(direction) });
  }});

  for (const item of items) {
    const el = document.createElement('div');
    el.className = 'fo-ctx-menu__item';
    el.textContent = item.label;
    el.addEventListener('click', ev => {
      ev.stopPropagation();
      item.action();
      menu.remove();
    });
    menu.appendChild(el);
  }

  canvasWrap.appendChild(menu);

  // Close on next click anywhere.
  const close = () => { menu.remove(); document.removeEventListener('click', close); };
  setTimeout(() => document.addEventListener('click', close), 0);
});

// ---------------------------------------------------------------------------
// Interaction mode helpers
// ---------------------------------------------------------------------------

function enterWaypointMode() {
  _interactionMode = { type: 'waypoint' };
  targetHint.textContent = 'Click map to set waypoint';
  targetHint.style.display = '';
  modeIndEl.textContent = 'WAYPOINT MODE';
  modeIndEl.style.display = '';
  mapPanelEl.classList.add('fo-map-panel--targeting');
}

function enterPatrolMode() {
  _interactionMode = { type: 'patrol', points: [] };
  targetHint.textContent = 'Click to add waypoints • Enter to confirm • Esc to cancel';
  targetHint.style.display = '';
  modeIndEl.textContent = 'PATROL ROUTE';
  modeIndEl.style.display = '';
  mapPanelEl.classList.add('fo-map-panel--targeting');
}

function enterDecoyMode() {
  _interactionMode = { type: 'decoy' };
  targetHint.textContent = 'Click map to deploy decoy in that direction';
  targetHint.style.display = '';
  modeIndEl.textContent = 'DECOY DEPLOY';
  modeIndEl.style.display = '';
  mapPanelEl.classList.add('fo-map-panel--targeting');
}

function enterTargetMode() {
  _interactionMode = { type: 'target' };
  targetHint.textContent = 'Click a contact to designate target';
  targetHint.style.display = '';
  modeIndEl.textContent = 'TARGET SELECT';
  modeIndEl.style.display = '';
  mapPanelEl.classList.add('fo-map-panel--targeting');
}

function exitInteractionMode() {
  _interactionMode = null;
  targetHint.style.display = 'none';
  modeIndEl.style.display = 'none';
  mapPanelEl.classList.remove('fo-map-panel--targeting');
  renderMap();
}

function confirmPatrolRoute() {
  if (!_interactionMode || _interactionMode.type !== 'patrol') return;
  const pts = _interactionMode.points;
  if (pts.length < 1 || !_selectedDroneId) {
    exitInteractionMode();
    return;
  }
  send('flight_ops.set_waypoints', {
    drone_id: _selectedDroneId,
    waypoints: pts,
  });
  SoundBank.play('scan_complete');
  exitInteractionMode();
}

// ---------------------------------------------------------------------------
// Drone selection
// ---------------------------------------------------------------------------

function selectDrone(droneId) {
  _selectedDroneId = droneId;
  renderDroneCards();
  renderHangarCards();
  renderMap();
}

// ---------------------------------------------------------------------------
// Drone cards — active drones
// ---------------------------------------------------------------------------

function renderDroneCards() {
  if (!foState) return;

  const activeDrones = foState.drones.filter(d => AIRBORNE_STATUSES.has(d.status));

  // Structural key: properties that affect card layout/buttons.
  // When only bar values change (fuel ticking down, etc.) we skip the full
  // DOM rebuild and update bars in-place, preventing button hover flicker.
  const structKey = activeDrones.length === 0 ? '__empty__' : activeDrones.map(d => [
    d.id, d.status, d.ai_behaviour, d.drone_type,
    d.engagement_rules, d.mission_type,
    d.bingo_acknowledged, d.id === _selectedDroneId,
    d.hull < d.max_hull, d.fuel <= FUEL_LOW,
    d.max_hull > 0 && (d.hull / d.max_hull * 100) <= HULL_LOW,
    d.contact_of_interest || '', d.escort_target || '',
    d.buoys_remaining, d.ecm_strength,
    (d.waypoints || []).length, d.waypoint_index,
    d.contacts_found, d.damage_dealt > 0, d.survivors_rescued,
    d.pickup_timer > 0,
  ].join('|')).join(';');

  if (structKey === _prevDroneStructKey) {
    _updateDroneBarsInPlace(activeDrones);
    return;
  }
  _prevDroneStructKey = structKey;

  droneCardsEl.innerHTML = '';

  if (activeDrones.length === 0) {
    droneCardsEl.innerHTML = '<p class="text-dim" style="padding:0.4rem 0.75rem;font-size:0.8rem">No drones airborne.</p>';
    return;
  }

  for (const drone of activeDrones) {
    const card = document.createElement('div');
    const isSelected = drone.id === _selectedDroneId;
    const isRecalled = drone.ai_behaviour === 'rtb';
    card.className = 'fo-drone-card';
    // Status-based border colour per spec.
    if (drone.status === 'emergency') card.classList.add('fo-drone-card--emergency');
    else if (drone.status === 'rtb' || isRecalled) card.classList.add('fo-drone-card--rtb');
    else card.classList.add(`fo-drone-card--${drone.drone_type}`);
    if (isSelected) card.classList.add('fo-drone-card--selected');
    card.addEventListener('click', e => {
      e.stopPropagation();
      selectDrone(drone.id);
    });

    // Header: callsign + type + status badge + recalled badge.
    const header = document.createElement('div');
    header.className = 'fo-drone-card__header';

    const callsign = document.createElement('span');
    callsign.className = 'fo-drone-callsign';
    callsign.textContent = drone.callsign || drone.id;

    const typeLabel = document.createElement('span');
    typeLabel.className = 'fo-drone-type-label';
    typeLabel.textContent = (drone.drone_type || '').replace('_', ' ');

    const badge = document.createElement('span');
    badge.className = `fo-drone-state-badge fo-drone-state-badge--${drone.status}`;
    badge.textContent = drone.status.toUpperCase();

    header.append(callsign, typeLabel, badge);

    // Recalled badge (active drone ordered to RTB).
    if (isRecalled && drone.status === 'active') {
      const recalledBadge = document.createElement('span');
      recalledBadge.className = 'fo-drone-state-badge fo-drone-state-badge--recalled';
      recalledBadge.textContent = 'RECALLED';
      header.appendChild(recalledBadge);
    }

    card.appendChild(header);

    // Mission info row.
    if (drone.mission_type || drone.ai_behaviour !== 'loiter' || drone.contact_of_interest || drone.escort_target) {
      const info = document.createElement('div');
      info.className = 'fo-drone-card__info';
      if (drone.mission_type) {
        const mt = document.createElement('span');
        mt.textContent = `Mission: ${drone.mission_type.toUpperCase()}`;
        info.appendChild(mt);
      }
      if (drone.engagement_rules && drone.engagement_rules !== 'weapons_hold') {
        const er = document.createElement('span');
        er.textContent = drone.engagement_rules.replace('_', ' ').toUpperCase();
        info.appendChild(er);
      }
      if (drone.contact_of_interest) {
        const coi = document.createElement('span');
        coi.textContent = `TGT: ${drone.contact_of_interest}`;
        info.appendChild(coi);
      }
      if (drone.escort_target) {
        const esc = document.createElement('span');
        esc.textContent = `ESC: ${drone.escort_target}`;
        info.appendChild(esc);
      }
      card.appendChild(info);
    }

    // Waypoint progress + time remaining + stats row.
    const detail = document.createElement('div');
    detail.className = 'fo-drone-card__info';
    const wps = drone.waypoints || [];
    if (wps.length > 0) {
      const wpSpan = document.createElement('span');
      wpSpan.textContent = `WP ${Math.min(drone.waypoint_index + 1, wps.length)}/${wps.length}`;
      detail.appendChild(wpSpan);
    }
    if (drone.fuel_consumption > 0) {
      const secs = drone.fuel / drone.fuel_consumption;
      const mins = Math.floor(secs / 60);
      const s = Math.floor(secs % 60);
      const timeSpan = document.createElement('span');
      timeSpan.textContent = `\u23F1 ~${mins}:${s.toString().padStart(2, '0')}`;
      detail.appendChild(timeSpan);
    }
    if (drone.drone_type === 'scout' && drone.contacts_found > 0) {
      const cfSpan = document.createElement('span');
      cfSpan.textContent = `Contacts: ${drone.contacts_found}`;
      detail.appendChild(cfSpan);
    }
    if (drone.drone_type === 'combat' && drone.damage_dealt > 0) {
      const ddSpan = document.createElement('span');
      ddSpan.textContent = `Dmg dealt: ${drone.damage_dealt.toFixed(1)}`;
      detail.appendChild(ddSpan);
    }
    if (drone.drone_type === 'rescue' && drone.survivors_rescued > 0) {
      const srSpan = document.createElement('span');
      srSpan.textContent = `Rescued: ${drone.survivors_rescued}`;
      detail.appendChild(srSpan);
    }
    if (detail.childElementCount > 0) card.appendChild(detail);

    // Bars.
    const bars = document.createElement('div');
    bars.className = 'fo-drone-card__bars';

    // Fuel bar.
    bars.appendChild(makeBar('FUEL', drone.fuel, 100,
      drone.fuel <= FUEL_LOW ? 'fo-bar-fill--fuel-low' : 'fo-bar-fill--fuel',
      null, `${drone.id}-fuel`));

    // Hull bar (only if damaged).
    if (drone.hull < drone.max_hull) {
      const hullPct = (drone.hull / drone.max_hull) * 100;
      bars.appendChild(makeBar('HULL', hullPct, 100,
        hullPct <= HULL_LOW ? 'fo-bar-fill--hull-low' : 'fo-bar-fill--hull',
        null, `${drone.id}-hull`));
    }

    // Ammo bar (combat drones).
    if (drone.drone_type === 'combat' && drone.ammo !== undefined) {
      bars.appendChild(makeBar('AMMO', drone.ammo, 100, 'fo-bar-fill--ammo',
        null, `${drone.id}-ammo`));
    }

    // Cargo bar (rescue drones).
    if (drone.drone_type === 'rescue' && drone.cargo_capacity > 0) {
      const cargoPct = (drone.cargo_current / drone.cargo_capacity) * 100;
      bars.appendChild(makeBar('CARGO', cargoPct, 100, 'fo-bar-fill--cargo',
        `${drone.cargo_current}/${drone.cargo_capacity}`, `${drone.id}-cargo`));
    }

    // Pickup progress bar (rescue drones actively picking up).
    if (drone.drone_type === 'rescue' && drone.pickup_timer > 0) {
      const pickupMax = 15; // RESCUE_PICKUP_TIME from server
      const pickupPct = (drone.pickup_timer / pickupMax) * 100;
      bars.appendChild(makeBar('PICKUP', pickupPct, 100, 'fo-bar-fill--cargo',
        `${Math.ceil(drone.pickup_timer)}/${pickupMax}s`, `${drone.id}-pickup`));
    }

    card.appendChild(bars);

    // ECM strength indicator (ecm drones).
    if (drone.drone_type === 'ecm_drone' && drone.ecm_strength > 0) {
      const ecmInfo = document.createElement('div');
      ecmInfo.className = 'fo-drone-card__info';
      const ecmSpan = document.createElement('span');
      ecmSpan.textContent = `ECM: ${Math.round(drone.ecm_strength * 100)}%`;
      ecmInfo.appendChild(ecmSpan);
      card.appendChild(ecmInfo);
    }

    // Buoy count (survey drones).
    if (drone.drone_type === 'survey' && drone.buoy_capacity > 0) {
      const buoyInfo = document.createElement('div');
      buoyInfo.className = 'fo-drone-card__info';
      const buoySpan = document.createElement('span');
      buoySpan.textContent = `Buoys: ${drone.buoys_remaining}/${drone.buoy_capacity}`;
      buoyInfo.appendChild(buoySpan);
      card.appendChild(buoyInfo);
    }

    // Bingo warning.
    if (drone.bingo_acknowledged) {
      const bingo = document.createElement('div');
      bingo.className = 'fo-bingo-warning';
      bingo.textContent = '\u26A0 BINGO FUEL';
      card.appendChild(bingo);
    }

    // Buttons.
    const btns = document.createElement('div');
    btns.className = 'fo-drone-card__btns';

    if (drone.status === 'active') {
      if (isRecalled) {
        // Already recalled — show indicator instead of Recall button.
        const retLabel = document.createElement('span');
        retLabel.className = 'fo-recalled-label';
        retLabel.textContent = 'RETURNING TO BASE';
        btns.appendChild(retLabel);
      } else {
        btns.appendChild(makeBtn('Recall', 'fo-btn fo-btn--warn', () => {
          send('flight_ops.recall_drone', { drone_id: drone.id });
        }));
        if (drone.drone_type === 'combat') {
          const rulesLabel = drone.engagement_rules === 'weapons_free' ? 'Hold' : 'W.Free';
          const nextRules = drone.engagement_rules === 'weapons_free' ? 'weapons_hold' : 'weapons_free';
          btns.appendChild(makeBtn(rulesLabel, 'fo-btn', () => {
            send('flight_ops.set_engagement_rules', { drone_id: drone.id, rules: nextRules });
          }));
          btns.appendChild(makeBtn('Target', 'fo-btn', () => {
            selectDrone(drone.id);
            enterTargetMode();
          }));
        }
        if (drone.drone_type === 'scout') {
          btns.appendChild(makeBtn('Track', 'fo-btn', () => {
            selectDrone(drone.id);
            enterTargetMode();
          }));
        }
        if (drone.drone_type === 'survey') {
          btns.appendChild(makeBtn('Buoy', 'fo-btn', () => {
            send('flight_ops.deploy_buoy', { drone_id: drone.id });
          }));
        }
      }
    } else if (drone.status === 'launching') {
      const launchSpan = document.createElement('span');
      launchSpan.className = 'fo-launching-label';
      launchSpan.textContent = 'LAUNCH SEQUENCE\u2026';
      btns.appendChild(launchSpan);
      btns.appendChild(makeBtn('Abort', 'fo-btn fo-btn--warn', () => {
        send('flight_ops.cancel_launch', { drone_id: drone.id });
      }));
    } else if (drone.status === 'rtb' || drone.status === 'recovering') {
      const retSpan = document.createElement('span');
      retSpan.className = 'text-dim text-label';
      retSpan.style.fontSize = '0.7rem';
      retSpan.textContent = drone.status === 'rtb' ? 'RETURNING\u2026' : 'RECOVERING\u2026';
      btns.appendChild(retSpan);
    }

    card.appendChild(btns);
    droneCardsEl.appendChild(card);
  }
}

/** Fast-path: update bar widths and percentage text without rebuilding DOM. */
function _updateDroneBarsInPlace(drones) {
  for (const d of drones) {
    const fuelFill = droneCardsEl.querySelector(`[data-bar="${d.id}-fuel"]`);
    if (fuelFill) {
      fuelFill.style.width = `${Math.max(0, Math.min(100, d.fuel))}%`;
      const pct = fuelFill.closest('.fo-bar-row').querySelector('.fo-bar-pct');
      if (pct) pct.textContent = `${Math.round(d.fuel)}%`;
    }
    const hullFill = droneCardsEl.querySelector(`[data-bar="${d.id}-hull"]`);
    if (hullFill) {
      const hullPct = d.max_hull > 0 ? (d.hull / d.max_hull) * 100 : 0;
      hullFill.style.width = `${Math.max(0, Math.min(100, hullPct))}%`;
      const pct = hullFill.closest('.fo-bar-row').querySelector('.fo-bar-pct');
      if (pct) pct.textContent = `${Math.round(hullPct)}%`;
    }
    const ammoFill = droneCardsEl.querySelector(`[data-bar="${d.id}-ammo"]`);
    if (ammoFill) {
      ammoFill.style.width = `${Math.max(0, Math.min(100, d.ammo))}%`;
      const pct = ammoFill.closest('.fo-bar-row').querySelector('.fo-bar-pct');
      if (pct) pct.textContent = `${Math.round(d.ammo)}%`;
    }
    const cargoFill = droneCardsEl.querySelector(`[data-bar="${d.id}-cargo"]`);
    if (cargoFill && d.cargo_capacity > 0) {
      const cargoPct = (d.cargo_current / d.cargo_capacity) * 100;
      cargoFill.style.width = `${Math.max(0, Math.min(100, cargoPct))}%`;
      const pct = cargoFill.closest('.fo-bar-row').querySelector('.fo-bar-pct');
      if (pct) pct.textContent = `${d.cargo_current}/${d.cargo_capacity}`;
    }
    const pickupFill = droneCardsEl.querySelector(`[data-bar="${d.id}-pickup"]`);
    if (pickupFill && d.pickup_timer > 0) {
      const pickupPct = (d.pickup_timer / 15) * 100;
      pickupFill.style.width = `${Math.max(0, Math.min(100, pickupPct))}%`;
      const pct = pickupFill.closest('.fo-bar-row').querySelector('.fo-bar-pct');
      if (pct) pct.textContent = `${Math.ceil(d.pickup_timer)}/15s`;
    }
  }
}

// ---------------------------------------------------------------------------
// Hangar cards
// ---------------------------------------------------------------------------

function renderHangarCards() {
  if (!foState) return;

  const hangarDrones = foState.drones.filter(d => HANGAR_STATUSES.has(d.status));
  const turnarounds = foState.flight_deck.turnarounds || {};

  // Structural key: properties that affect card buttons/layout.
  const structKey = hangarDrones.length === 0 ? '__empty__' : hangarDrones.map(d => {
    const ta = turnarounds[d.id];
    const taRemaining = ta ? ta.total_remaining : undefined;
    const isReady = d.status === 'hangar' && (taRemaining === undefined || taRemaining <= 0);
    const hasTurnaround = taRemaining !== undefined && taRemaining > 0;
    return [d.id, d.status, isReady, hasTurnaround].join('|');
  }).join(';');

  if (structKey === _prevHangarStructKey) {
    _updateHangarBarsInPlace(hangarDrones, turnarounds);
    return;
  }
  _prevHangarStructKey = structKey;

  hangarCardsEl.innerHTML = '';

  if (hangarDrones.length === 0) {
    hangarCardsEl.innerHTML = '<p class="text-dim" style="padding:0.4rem 0.75rem;font-size:0.8rem">Hangar empty.</p>';
    return;
  }

  for (const drone of hangarDrones) {
    const card = document.createElement('div');
    card.className = 'fo-hangar-card';

    const header = document.createElement('div');
    header.className = 'fo-hangar-card__header';

    const callsign = document.createElement('span');
    callsign.className = 'fo-hangar-callsign';
    callsign.textContent = `${drone.callsign || drone.id} (${(drone.drone_type || '').replace('_', ' ')})`;

    header.appendChild(callsign);

    const ta = turnarounds[drone.id];
    const taRemaining = ta ? ta.total_remaining : undefined;
    if (drone.status === 'hangar' && (taRemaining === undefined || taRemaining <= 0)) {
      // Ready to launch.
      const ready = document.createElement('span');
      ready.className = 'fo-hangar-ready';
      ready.textContent = 'READY';
      header.appendChild(ready);

      card.appendChild(header);

      const btns = document.createElement('div');
      btns.className = 'fo-drone-card__btns';
      btns.style.marginTop = '0.2rem';
      btns.appendChild(makeBtn('Launch', 'fo-btn', () => {
        send('flight_ops.launch_drone', { drone_id: drone.id });
        SoundBank.play('scan_complete');
      }));
      card.appendChild(btns);
    } else {
      // Turnaround in progress.
      const taLabel = document.createElement('span');
      taLabel.className = 'fo-hangar-turnaround';
      taLabel.setAttribute('data-ta-label', drone.id);
      taLabel.textContent = taRemaining !== undefined ? `TURNAROUND ${Math.ceil(taRemaining)}s` : drone.status.toUpperCase();
      header.appendChild(taLabel);
      card.appendChild(header);

      if (ta && taRemaining > 0) {
        // Per-sub-task progress bars.
        const subBars = document.createElement('div');
        subBars.className = 'fo-turnaround-sub-bars';
        if (ta.needs_refuel) {
          subBars.appendChild(makeTASubBar('FUEL', ta.refuel_remaining, 15, `${drone.id}-ta-fuel`));
        }
        if (ta.needs_rearm) {
          subBars.appendChild(makeTASubBar('REARM', ta.rearm_remaining, 20, `${drone.id}-ta-rearm`));
        }
        if (ta.needs_repair) {
          subBars.appendChild(makeTASubBar('REPAIR', ta.repair_remaining, ta.repair_remaining + 1, `${drone.id}-ta-repair`));
        }
        card.appendChild(subBars);

        // Overall progress bar.
        const maxTA = 30;
        const pct = Math.max(0, Math.min(100, ((maxTA - taRemaining) / maxTA) * 100));
        const barWrap = document.createElement('div');
        barWrap.className = 'fo-turnaround-bar';
        const barFill = document.createElement('div');
        barFill.className = 'fo-turnaround-bar-fill';
        barFill.setAttribute('data-ta', drone.id);
        barFill.style.width = `${pct}%`;
        barWrap.appendChild(barFill);
        card.appendChild(barWrap);

        const btns = document.createElement('div');
        btns.className = 'fo-drone-card__btns';
        btns.style.marginTop = '0.2rem';
        // Rush button — skip incomplete sub-tasks.
        const skipList = [];
        if (ta.needs_rearm && ta.rearm_remaining > 0) skipList.push('rearm');
        if (ta.needs_repair && ta.repair_remaining > 0) skipList.push('repair');
        btns.appendChild(makeBtn('Rush', 'fo-btn fo-btn--warn', () => {
          send('flight_ops.rush_turnaround', { drone_id: drone.id, skip: skipList });
        }));
        card.appendChild(btns);
      }
    }

    hangarCardsEl.appendChild(card);
  }
}

/** Fast-path: update turnaround bar widths and labels without rebuilding DOM. */
function _updateHangarBarsInPlace(drones, turnarounds) {
  for (const d of drones) {
    const ta = turnarounds[d.id];
    const taRemaining = ta ? ta.total_remaining : undefined;
    const taFill = hangarCardsEl.querySelector(`[data-ta="${d.id}"]`);
    if (taFill && taRemaining !== undefined && taRemaining > 0) {
      const maxTA = 30;
      const pct = Math.max(0, Math.min(100, ((maxTA - taRemaining) / maxTA) * 100));
      taFill.style.width = `${pct}%`;
    }
    const taLabel = hangarCardsEl.querySelector(`[data-ta-label="${d.id}"]`);
    if (taLabel && taRemaining !== undefined) {
      taLabel.textContent = `TURNAROUND ${Math.ceil(taRemaining)}s`;
    }
    // Update sub-task bars.
    if (ta) {
      _updateTASubBar(d.id, 'fuel', ta.refuel_remaining, 15);
      _updateTASubBar(d.id, 'rearm', ta.rearm_remaining, 20);
      _updateTASubBar(d.id, 'repair', ta.repair_remaining, ta.repair_remaining + 1);
    }
  }
}

function _updateTASubBar(droneId, step, remaining, max) {
  const fill = hangarCardsEl.querySelector(`[data-ta-sub="${droneId}-ta-${step}"]`);
  if (!fill) return;
  const pct = Math.max(0, Math.min(100, ((max - remaining) / max) * 100));
  fill.style.width = `${pct}%`;
  const lbl = fill.closest('.fo-ta-sub-row')?.querySelector('.fo-ta-sub-time');
  if (lbl) lbl.textContent = remaining > 0 ? `${Math.ceil(remaining)}s` : 'DONE';
}

// ---------------------------------------------------------------------------
// Expendables
// ---------------------------------------------------------------------------

function renderExpendables() {
  if (!foState) return;

  decoyStockEl.textContent = `DECOYS: ${foState.decoy_stock}`;
  deployDecoyBtn.disabled = foState.decoy_stock <= 0;

  buoyListEl.innerHTML = '';
  if (foState.buoys.length === 0) {
    buoyListEl.innerHTML = '<p class="text-dim" style="padding:0.2rem 0.75rem;font-size:0.75rem">No buoys deployed.</p>';
  } else {
    for (const b of foState.buoys) {
      if (!b.active) continue;
      const row = document.createElement('div');
      row.className = 'fo-buoy-row';
      const id = document.createElement('span');
      id.className = 'fo-buoy-id';
      id.textContent = b.id.toUpperCase();
      const coords = document.createElement('span');
      coords.textContent = `(${Math.round(b.x)}, ${Math.round(b.y)})`;
      row.append(id, coords);
      buoyListEl.appendChild(row);
    }
  }
}

deployDecoyBtn.addEventListener('click', () => {
  if (!foState || foState.decoy_stock <= 0) return;
  if (_interactionMode?.type === 'decoy') {
    exitInteractionMode();
  } else {
    if (_interactionMode) exitInteractionMode();
    enterDecoyMode();
  }
});

// ---------------------------------------------------------------------------
// Carrier panel (carrier-class only)
// ---------------------------------------------------------------------------

function renderCarrierPanel() {
  const el = document.getElementById('carrier-panel');
  if (!el) return;
  if (!_carrierState || !_carrierState.active) { el.style.display = 'none'; return; }
  el.style.display = '';
  const sq = _carrierState.squadrons || {};
  const sqCount = Object.keys(sq).length;
  const cap = _carrierState.cap_zone;
  const scramble = _carrierState.scramble_active ? 'ACTIVE' : 'OFF';
  const capInfo = cap && cap.active ? `R:${cap.radius} (${cap.assigned_drone_ids.length} drones)` : 'NONE';
  el.innerHTML =
    `<div class="panel-header">CARRIER OPS</div>` +
    `<div class="panel-body">` +
    `<div>Squadrons: ${sqCount}</div>` +
    `<div>CAP zone: ${capInfo}</div>` +
    `<div>Scramble: ${scramble}${_carrierState.scramble_queue_remaining ? ' (' + _carrierState.scramble_queue_remaining + ' queued)' : ''}</div>` +
    `</div>`;
}

// ---------------------------------------------------------------------------
// Status bar
// ---------------------------------------------------------------------------

function renderStatusBar() {
  if (!foState) return;

  const drones = foState.drones;
  const active = drones.filter(d => AIRBORNE_STATUSES.has(d.status)).length;
  const total = drones.length;
  const hangarReady = drones.filter(d => d.status === 'hangar').length;
  const maintenance = drones.filter(d => HANGAR_STATUSES.has(d.status) && d.status !== 'hangar').length;
  const fd = foState.flight_deck;

  const parts = [];
  parts.push(`ACTIVE: ${active}/${total}`);
  parts.push(`HANGAR: ${hangarReady} ready${maintenance ? `, ${maintenance} turnaround` : ''}`);
  parts.push(`DECK: ${fd.deck_status === 'operational' ? '\u2713 OPS' : '\u2717 ' + fd.deck_status.toUpperCase()}`);
  parts.push(`FUEL: ${Math.round(fd.drone_fuel_reserve)}%`);
  parts.push(`AMMO: ${Math.round(fd.drone_ammo_reserve)}%`);
  parts.push(`BUOYS: ${foState.buoys.filter(b => b.active).length}`);
  parts.push(`DECOYS: ${foState.decoy_stock}`);
  if (_sensorContacts.length > 0) {
    const hostiles = _sensorContacts.filter(c => c.classification === 'hostile').length;
    const unknowns = _sensorContacts.filter(c => c.classification === 'unknown').length;
    let detail = '';
    if (hostiles || unknowns) {
      const parts2 = [];
      if (hostiles) parts2.push(`${hostiles} hostile`);
      if (unknowns) parts2.push(`${unknowns} unknown`);
      detail = ` (${parts2.join(', ')})`;
    }
    parts.push(`CONTACTS: ${_sensorContacts.length}${detail}`);
  }

  // Warnings.
  const warnings = [];
  for (const d of drones) {
    if (d.bingo_acknowledged) {
      warnings.push(`\u26A0 ${d.callsign || d.id} BINGO FUEL`);
    }
  }
  if (fd.fire_active) warnings.push('\u26A0 DECK FIRE');
  if (fd.depressurised) warnings.push('\u26A0 DEPRESSURISED');
  if (fd.crash_block_remaining > 0) warnings.push(`\u26A0 CRASH BLOCK ${Math.ceil(fd.crash_block_remaining)}s`);

  statusBarEl.innerHTML = '';
  for (const p of parts) {
    const span = document.createElement('span');
    span.textContent = p;
    statusBarEl.appendChild(span);
  }
  for (const w of warnings) {
    const span = document.createElement('span');
    span.className = 'fo-status-warning';
    span.textContent = w;
    statusBarEl.appendChild(span);
  }
}

// ---------------------------------------------------------------------------
// Keyboard shortcuts
// ---------------------------------------------------------------------------

document.addEventListener('keydown', e => {
  // Escape — cancel mode.
  if (e.key === 'Escape') {
    if (_interactionMode) {
      exitInteractionMode();
      return;
    }
    if (_cameraOverride || _droneCentredView) {
      _cameraOverride = null;
      _droneCentredView = false;
      renderMap();
      return;
    }
    if (_selectedDroneId) {
      _selectedDroneId = null;
      renderDroneCards();
      renderHangarCards();
      renderMap();
      return;
    }
  }

  // Enter — confirm patrol route.
  if (e.key === 'Enter' && _interactionMode?.type === 'patrol') {
    e.preventDefault();
    confirmPatrolRoute();
    return;
  }

  // Don't process shortcuts when focused on an input.
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  // Digit keys — select drone by index.
  if (e.key >= '1' && e.key <= '9') {
    const idx = parseInt(e.key) - 1;
    if (foState && idx < foState.drones.length) {
      selectDrone(foState.drones[idx].id);
    }
    return;
  }

  const key = e.key.toLowerCase();

  // L — launch selected hangar drone.
  if (key === 'l' && _selectedDroneId) {
    const drone = foState?.drones.find(d => d.id === _selectedDroneId);
    if (drone?.status === 'hangar') {
      send('flight_ops.launch_drone', { drone_id: _selectedDroneId });
      SoundBank.play('scan_complete');
    }
    return;
  }

  // R — recall selected active drone.
  if (key === 'r' && _selectedDroneId) {
    const drone = foState?.drones.find(d => d.id === _selectedDroneId);
    if (drone?.status === 'active') {
      send('flight_ops.recall_drone', { drone_id: _selectedDroneId });
    }
    return;
  }

  // W — waypoint mode.
  if (key === 'w') {
    if (_interactionMode) exitInteractionMode();
    else enterWaypointMode();
    return;
  }

  // P — patrol route mode.
  if (key === 'p') {
    if (_interactionMode?.type === 'patrol') exitInteractionMode();
    else {
      if (_interactionMode) exitInteractionMode();
      enterPatrolMode();
    }
    return;
  }

  // E — toggle engagement rules.
  if (key === 'e' && _selectedDroneId) {
    const drone = foState?.drones.find(d => d.id === _selectedDroneId);
    if (drone?.drone_type === 'combat') {
      const nextRules = drone.engagement_rules === 'weapons_free' ? 'weapons_hold' : 'weapons_free';
      send('flight_ops.set_engagement_rules', { drone_id: _selectedDroneId, rules: nextRules });
    }
    return;
  }

  // T — target designation mode.
  if (key === 't' && _selectedDroneId) {
    if (_interactionMode?.type === 'target') exitInteractionMode();
    else {
      if (_interactionMode) exitInteractionMode();
      enterTargetMode();
    }
    return;
  }

  // D — deploy decoy.
  if (key === 'd') {
    if (_interactionMode?.type === 'decoy') exitInteractionMode();
    else {
      if (_interactionMode) exitInteractionMode();
      enterDecoyMode();
    }
    return;
  }

  // B — deploy buoy.
  if (key === 'b' && _selectedDroneId) {
    const drone = foState?.drones.find(d => d.id === _selectedDroneId);
    if (drone?.drone_type === 'survey' && drone.status === 'active') {
      send('flight_ops.deploy_buoy', { drone_id: _selectedDroneId });
    }
    return;
  }

  // C — clear to land.
  if (key === 'c' && _selectedDroneId) {
    send('flight_ops.clear_to_land', { drone_id: _selectedDroneId });
    return;
  }

  // F — focus on selected drone (centre map on drone position).
  if (key === 'f' && _selectedDroneId && foState) {
    const drone = foState.drones.find(d => d.id === _selectedDroneId);
    if (drone && AIRBORNE_STATUSES.has(drone.status)) {
      _cameraOverride = { x: drone.x, y: drone.y };
      _droneCentredView = false;
      renderMap();
    }
    return;
  }

  // Space — toggle between ship-centred and drone-centred map view.
  if (e.key === ' ' || e.key === 'Space') {
    e.preventDefault();
    if (_droneCentredView) {
      _droneCentredView = false;
      _cameraOverride = null;
    } else if (_selectedDroneId) {
      _droneCentredView = true;
      _cameraOverride = null;
    }
    renderMap();
    return;
  }

  // Tab — cycle drone selection.
  if (e.key === 'Tab' && foState) {
    e.preventDefault();
    const ids = foState.drones.map(d => d.id);
    if (ids.length === 0) return;
    const cur = ids.indexOf(_selectedDroneId);
    const next = (cur + 1) % ids.length;
    selectDrone(ids[next]);
    return;
  }
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeBar(label, value, max, fillClass, customText, dataKey) {
  const row = document.createElement('div');
  row.className = 'fo-bar-row';

  const lbl = document.createElement('span');
  lbl.className = 'fo-bar-label';
  lbl.textContent = label;

  const wrap = document.createElement('div');
  wrap.className = 'fo-bar-wrap';
  const fill = document.createElement('div');
  fill.className = `fo-bar-fill ${fillClass}`;
  if (dataKey) fill.setAttribute('data-bar', dataKey);
  fill.style.width = `${Math.max(0, Math.min(100, (value / max) * 100))}%`;
  wrap.appendChild(fill);

  const pct = document.createElement('span');
  pct.className = 'fo-bar-pct';
  pct.textContent = customText || `${Math.round(value)}%`;

  row.append(lbl, wrap, pct);
  return row;
}

function makeTASubBar(label, remaining, max, dataKey) {
  const row = document.createElement('div');
  row.className = 'fo-ta-sub-row';
  const lbl = document.createElement('span');
  lbl.className = 'fo-ta-sub-label';
  lbl.textContent = label;
  const wrap = document.createElement('div');
  wrap.className = 'fo-ta-sub-wrap';
  const fill = document.createElement('div');
  fill.className = 'fo-ta-sub-fill';
  fill.setAttribute('data-ta-sub', dataKey);
  const pct = Math.max(0, Math.min(100, ((max - remaining) / max) * 100));
  fill.style.width = `${pct}%`;
  wrap.appendChild(fill);
  const time = document.createElement('span');
  time.className = 'fo-ta-sub-time';
  time.textContent = remaining > 0 ? `${Math.ceil(remaining)}s` : 'DONE';
  row.append(lbl, wrap, time);
  return row;
}

function makeBtn(text, className, onClick) {
  const btn = document.createElement('button');
  btn.className = className;
  btn.textContent = text;
  btn.addEventListener('click', e => {
    e.stopPropagation();
    onClick();
  });
  return btn;
}
