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

// Currently selected drone id.
let _selectedDroneId = null;

// Interaction mode:
//   null                          — idle
//   { type: 'waypoint' }          — click map to set waypoint
//   { type: 'patrol', points: [] }— ctrl+click to add patrol waypoints
//   { type: 'target' }            — click contact to designate target
//   { type: 'decoy' }             — click map to set decoy direction
let _interactionMode = null;

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
  },
  onGameOver(payload) {
    standbyEl.style.display = '';
    mainEl.style.display    = 'none';
    statusBarWrap.style.display = 'none';
    missionLabel.textContent = 'MISSION ENDED';
    foState = null;
    shipState = null;
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

function worldToCanvas(wx, wy) {
  if (!shipState) return { cx: 0, cy: 0 };
  const w = mapCanvas.width;
  const h = mapCanvas.height;
  const scale = Math.min(w, h) / 2 / _mapWorldRadius;
  return {
    cx: w / 2 + (wx - shipState.position.x) * scale,
    cy: h / 2 + (wy - shipState.position.y) * scale,
  };
}

function canvasToWorld(px, py) {
  if (!shipState) return { wx: 0, wy: 0 };
  const w = mapCanvas.width;
  const h = mapCanvas.height;
  const scale = Math.min(w, h) / 2 / _mapWorldRadius;
  return {
    wx: shipState.position.x + (px - w / 2) / scale,
    wy: shipState.position.y + (py - h / 2) / scale,
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
  drawDecoys();
  drawBuoys();
  drawDroneRoutes();
  drawDrones();
  drawShip(w / 2, h / 2, shipState.heading);
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

function drawSensorCoverage() {
  const scale = worldScale();

  // Drone sensor bubbles (scouts and surveys when active).
  for (const d of foState.drones) {
    if (!AIRBORNE_STATUSES.has(d.status)) continue;
    if (d.drone_type !== 'scout' && d.drone_type !== 'survey') continue;
    const colour = TYPE_COLOURS[d.drone_type] || '#888';
    const range = 5_000 * scale;
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

  // Buoy coverage.
  for (const b of foState.buoys) {
    if (!b.active) continue;
    const range = 8_000 * scale;
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
    ctx.font = '9px monospace';
    ctx.fillText(`${Math.round(d.lifetime)}s`, cx + 5, cy + 3);
  }
}

function drawBuoys() {
  for (const b of foState.buoys) {
    if (!b.active) continue;
    const { cx, cy } = worldToCanvas(b.x, b.y);
    drawDiamond(cx, cy, 4, '#ffb000');
    ctx.fillStyle = '#ffb000';
    ctx.font = '9px monospace';
    ctx.fillText('BUOY', cx + 6, cy + 3);
  }
}

function drawDroneRoutes() {
  // Draw waypoint routes for selected drone.
  if (!_selectedDroneId) return;
  const drone = foState.drones.find(d => d.id === _selectedDroneId);
  if (!drone || !AIRBORNE_STATUSES.has(drone.status)) return;

  // If drone has waypoints (from mission), draw them.
  // For now we just draw a line from drone to its loiter/contact.
  // Waypoint data isn't in build_state yet — that's Part 7.
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
      ctx.font = '9px monospace';
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
    ctx.font = '9px monospace';
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
    return;
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
  droneCardsEl.innerHTML = '';

  const activeDrones = foState.drones.filter(d => AIRBORNE_STATUSES.has(d.status));
  if (activeDrones.length === 0) {
    droneCardsEl.innerHTML = '<p class="text-dim" style="padding:0.4rem 0.75rem;font-size:0.8rem">No drones airborne.</p>';
    return;
  }

  for (const drone of activeDrones) {
    const card = document.createElement('div');
    const isSelected = drone.id === _selectedDroneId;
    card.className = 'fo-drone-card';
    if (isSelected) card.classList.add('fo-drone-card--selected');
    card.addEventListener('click', e => {
      e.stopPropagation();
      selectDrone(drone.id);
    });

    // Header: callsign + type + status badge.
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
    card.appendChild(header);

    // Mission info row.
    if (drone.mission_type || drone.ai_behaviour !== 'idle') {
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
      card.appendChild(info);
    }

    // Bars.
    const bars = document.createElement('div');
    bars.className = 'fo-drone-card__bars';

    // Fuel bar.
    bars.appendChild(makeBar('FUEL', drone.fuel, 100,
      drone.fuel <= FUEL_LOW ? 'fo-bar-fill--fuel-low' : 'fo-bar-fill--fuel'));

    // Hull bar (only if damaged).
    if (drone.hull < drone.max_hull) {
      const hullPct = (drone.hull / drone.max_hull) * 100;
      bars.appendChild(makeBar('HULL', hullPct, 100,
        hullPct <= HULL_LOW ? 'fo-bar-fill--hull-low' : 'fo-bar-fill--hull'));
    }

    // Ammo bar (combat drones).
    if (drone.drone_type === 'combat' && drone.ammo !== undefined) {
      bars.appendChild(makeBar('AMMO', drone.ammo, 100, 'fo-bar-fill--ammo'));
    }

    // Cargo bar (rescue drones).
    if (drone.drone_type === 'rescue' && drone.cargo_capacity > 0) {
      const cargoPct = (drone.cargo_current / drone.cargo_capacity) * 100;
      bars.appendChild(makeBar('CARGO', cargoPct, 100, 'fo-bar-fill--cargo',
        `${drone.cargo_current}/${drone.cargo_capacity}`));
    }

    card.appendChild(bars);

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
      btns.appendChild(makeBtn('Recall', 'fo-btn fo-btn--warn', () => {
        send('flight_ops.recall_drone', { drone_id: drone.id });
      }));
      if (drone.drone_type === 'combat') {
        const rulesLabel = drone.engagement_rules === 'weapons_free' ? 'Hold' : 'W.Free';
        const nextRules = drone.engagement_rules === 'weapons_free' ? 'weapons_hold' : 'weapons_free';
        btns.appendChild(makeBtn(rulesLabel, 'fo-btn', () => {
          send('flight_ops.set_engagement_rules', { drone_id: drone.id, rules: nextRules });
        }));
      }
      if (drone.drone_type === 'survey') {
        btns.appendChild(makeBtn('Buoy', 'fo-btn', () => {
          send('flight_ops.deploy_buoy', { drone_id: drone.id });
        }));
      }
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

// ---------------------------------------------------------------------------
// Hangar cards
// ---------------------------------------------------------------------------

function renderHangarCards() {
  if (!foState) return;
  hangarCardsEl.innerHTML = '';

  const hangarDrones = foState.drones.filter(d => HANGAR_STATUSES.has(d.status));
  if (hangarDrones.length === 0) {
    hangarCardsEl.innerHTML = '<p class="text-dim" style="padding:0.4rem 0.75rem;font-size:0.8rem">Hangar empty.</p>';
    return;
  }

  const turnarounds = foState.flight_deck.turnarounds || {};

  for (const drone of hangarDrones) {
    const card = document.createElement('div');
    card.className = 'fo-hangar-card';

    const header = document.createElement('div');
    header.className = 'fo-hangar-card__header';

    const callsign = document.createElement('span');
    callsign.className = 'fo-hangar-callsign';
    callsign.textContent = `${drone.callsign || drone.id} (${(drone.drone_type || '').replace('_', ' ')})`;

    header.appendChild(callsign);

    const taRemaining = turnarounds[drone.id];
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
      const ta = document.createElement('span');
      ta.className = 'fo-hangar-turnaround';
      ta.textContent = taRemaining !== undefined ? `TURNAROUND ${Math.ceil(taRemaining)}s` : drone.status.toUpperCase();
      header.appendChild(ta);
      card.appendChild(header);

      if (taRemaining !== undefined && taRemaining > 0) {
        // Progress bar — approximate max of 30s for turnaround.
        const maxTA = 30;
        const pct = Math.max(0, Math.min(100, ((maxTA - taRemaining) / maxTA) * 100));
        const barWrap = document.createElement('div');
        barWrap.className = 'fo-turnaround-bar';
        const barFill = document.createElement('div');
        barFill.className = 'fo-turnaround-bar-fill';
        barFill.style.width = `${pct}%`;
        barWrap.appendChild(barFill);
        card.appendChild(barWrap);

        const btns = document.createElement('div');
        btns.className = 'fo-drone-card__btns';
        btns.style.marginTop = '0.2rem';
        btns.appendChild(makeBtn('Rush', 'fo-btn fo-btn--warn', () => {
          send('flight_ops.rush_turnaround', { drone_id: drone.id });
        }));
        card.appendChild(btns);
      }
    }

    hangarCardsEl.appendChild(card);
  }
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

  // F — focus on selected drone.
  if (key === 'f' && _selectedDroneId) {
    // For now just re-render with selection highlight.
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

function makeBar(label, value, max, fillClass, customText) {
  const row = document.createElement('div');
  row.className = 'fo-bar-row';

  const lbl = document.createElement('span');
  lbl.className = 'fo-bar-label';
  lbl.textContent = label;

  const wrap = document.createElement('div');
  wrap.className = 'fo-bar-wrap';
  const fill = document.createElement('div');
  fill.className = `fo-bar-fill ${fillClass}`;
  fill.style.width = `${Math.max(0, Math.min(100, (value / max) * 100))}%`;
  wrap.appendChild(fill);

  const pct = document.createElement('span');
  pct.className = 'fo-bar-pct';
  pct.textContent = customText || `${Math.round(value)}%`;

  row.append(lbl, wrap, pct);
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
