/**
 * Flight Operations Station
 *
 * - Sector map: top-down view of the sector showing ship position, drones, probes.
 * - Drone cards: fuel bars, state badges, LAUNCH / RECALL buttons.
 * - Probe panel: stock counter, DEPLOY button, list of deployed probes.
 *
 * Interaction flow:
 *   LAUNCH → drone enters target-select mode → operator clicks map → sends launch_drone
 *   RECALL → sends recall_drone immediately
 *   DEPLOY PROBE → enters target-select mode → operator clicks map → sends deploy_probe
 */

import { initSharedUI, on, send } from '../shared/station_base.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAP_WORLD_RADIUS = 60_000;   // world units visible from centre
const DRONE_FUEL_LOW   = 20.0;     // matches server DRONE_LOW_FUEL

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const standbyEl    = document.querySelector('[data-standby]');
const mainEl       = document.querySelector('[data-fo-main]');
const missionLabel = document.getElementById('mission-label');

const mapCanvas    = document.getElementById('fo-map');
const mapPanelEl   = document.getElementById('fo-map-panel');
const canvasWrap   = document.getElementById('fo-canvas-wrap');
const mapCoordEl   = document.getElementById('fo-map-coord');
const targetHint   = document.getElementById('fo-target-hint');
const droneCardsEl = document.getElementById('fo-drone-cards');
const probeStockEl = document.getElementById('fo-probe-stock');
const probeListEl  = document.getElementById('fo-probe-list');
const deployBtnEl  = document.getElementById('fo-deploy-btn');
const probeModeEl  = document.getElementById('fo-probe-mode-hint');

const ctx = mapCanvas.getContext('2d');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let shipState = null;    // latest ship.state payload
let foState   = null;    // latest flight_ops.state payload

// target-select mode:
//   null         — idle
//   { type: 'drone', droneId }
//   { type: 'probe' }
let targetMode = null;

// ---------------------------------------------------------------------------
// Shared UI init
// ---------------------------------------------------------------------------

initSharedUI({
  role: 'flight_ops',
  onConnect() {},
  onDisconnect() {},
  onGameStarted(payload) {
    standbyEl.style.display = 'none';
    mainEl.style.display    = 'grid';
    if (payload.mission_name) missionLabel.textContent = payload.mission_name;
    resizeCanvas();
  },
  onGameOver() {
    standbyEl.style.display = '';
    mainEl.style.display    = 'none';
    missionLabel.textContent = 'MISSION ENDED';
    foState = null;
    shipState = null;
  },
});

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

on('ship.state', payload => {
  shipState = payload;
  renderMap();
});

on('flight_ops.state', payload => {
  foState = payload;
  renderDroneCards();
  renderProbePanel();
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
// Sector map rendering
// ---------------------------------------------------------------------------

function worldToCanvas(wx, wy) {
  if (!shipState) return { cx: 0, cy: 0 };
  const w = mapCanvas.width;
  const h = mapCanvas.height;
  const cx = w / 2;
  const cy = h / 2;
  const scale = Math.min(w, h) / 2 / MAP_WORLD_RADIUS;
  return {
    cx: cx + (wx - shipState.position.x) * scale,
    cy: cy + (wy - shipState.position.y) * scale,
  };
}

function canvasToWorld(px, py) {
  if (!shipState) return { wx: 0, wy: 0 };
  const w = mapCanvas.width;
  const h = mapCanvas.height;
  const cx = w / 2;
  const cy = h / 2;
  const scale = Math.min(w, h) / 2 / MAP_WORLD_RADIUS;
  return {
    wx: shipState.position.x + (px - cx) / scale,
    wy: shipState.position.y + (py - cy) / scale,
  };
}

function renderMap() {
  const w = mapCanvas.width;
  const h = mapCanvas.height;
  if (!w || !h) return;

  ctx.clearRect(0, 0, w, h);

  // Background
  ctx.fillStyle = '#060e06';
  ctx.fillRect(0, 0, w, h);

  if (!foState) return;

  // Grid rings
  drawGrid();

  // Probe sensor bubbles
  for (const p of foState.probes) {
    drawSensorBubble(p.x, p.y, 8_000, '#ffb000', 0.08);
  }

  // Drone sensor bubbles (deployed only)
  for (const d of foState.drones) {
    if (d.state === 'deployed') {
      // Range: use ship flight_deck efficiency from ship.state; fall back to 1.0
      const eff = shipState?.systems?.flight_deck?.efficiency ?? 1.0;
      const range = 5_000 * eff;
      drawSensorBubble(d.x, d.y, range, '#4fc3f7', 0.08);
    }
  }

  // Probes
  for (const p of foState.probes) {
    const { cx, cy } = worldToCanvas(p.x, p.y);
    drawDiamond(ctx, cx, cy, 5, '#ffb000');
  }

  // Drones
  for (const d of foState.drones) {
    if (d.state === 'hangar') continue;
    const { cx, cy } = worldToCanvas(d.x, d.y);
    const colour = droneColour(d.state);
    // Draw drone triangle
    ctx.save();
    ctx.translate(cx, cy);
    ctx.beginPath();
    ctx.moveTo(0, -5);
    ctx.lineTo(4, 5);
    ctx.lineTo(-4, 5);
    ctx.closePath();
    ctx.fillStyle = colour;
    ctx.fill();
    ctx.restore();
    // Label
    ctx.fillStyle = colour;
    ctx.font = '9px monospace';
    ctx.fillText(d.id, cx + 6, cy - 2);
    // Target line in transit mode
    if (d.state === 'transit') {
      const { cx: tx, cy: ty } = worldToCanvas(d.target_x, d.target_y);
      ctx.strokeStyle = 'rgba(79,195,247,0.25)';
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(tx, ty);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // Ship (always at centre)
  if (shipState) {
    const cx = w / 2;
    const cy = h / 2;
    drawShip(cx, cy, shipState.heading);
  }

  // Targeting reticle if in target-select mode
  if (targetMode) {
    ctx.strokeStyle = 'rgba(0,255,65,0.4)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.strokeRect(0, 0, w, h);
    ctx.setLineDash([]);
  }
}

function drawGrid() {
  const w = mapCanvas.width;
  const h = mapCanvas.height;
  const scale = Math.min(w, h) / 2 / MAP_WORLD_RADIUS;
  const cx = w / 2;
  const cy = h / 2;

  ctx.strokeStyle = 'rgba(0,255,65,0.04)';
  ctx.lineWidth = 1;

  for (const ring of [10_000, 20_000, 40_000]) {
    ctx.beginPath();
    ctx.arc(cx, cy, ring * scale, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function drawSensorBubble(wx, wy, range, colour, alpha) {
  const { cx, cy } = worldToCanvas(wx, wy);
  const w = mapCanvas.width;
  const h = mapCanvas.height;
  const scale = Math.min(w, h) / 2 / MAP_WORLD_RADIUS;

  ctx.beginPath();
  ctx.arc(cx, cy, range * scale, 0, Math.PI * 2);
  ctx.fillStyle = colour.replace(')', `, ${alpha})`).replace('rgb', 'rgba');
  // Use simpler approach: set globalAlpha
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.fillStyle = colour;
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.strokeStyle = colour;
  ctx.lineWidth = 0.5;
  ctx.stroke();
  ctx.restore();
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
  ctx.fillStyle = 'var(--primary, #00ff41)';
  ctx.fill();
  ctx.restore();
}

function drawDiamond(ctx, cx, cy, r, colour) {
  ctx.beginPath();
  ctx.moveTo(cx, cy - r);
  ctx.lineTo(cx + r, cy);
  ctx.lineTo(cx, cy + r);
  ctx.lineTo(cx - r, cy);
  ctx.closePath();
  ctx.fillStyle = colour;
  ctx.fill();
}

function droneColour(state) {
  switch (state) {
    case 'transit':   return '#4fc3f7';
    case 'deployed':  return '#00ff41';
    case 'returning': return '#ffb000';
    default:          return '#888';
  }
}

// ---------------------------------------------------------------------------
// Map mouse interactions
// ---------------------------------------------------------------------------

canvasWrap.addEventListener('click', e => {
  if (!targetMode) return;

  const rect = canvasWrap.getBoundingClientRect();
  const px = e.clientX - rect.left;
  const py = e.clientY - rect.top;
  const { wx, wy } = canvasToWorld(px, py);

  if (targetMode.type === 'drone') {
    send('flight_ops.launch_drone', {
      drone_id: targetMode.droneId,
      target_x: Math.round(wx),
      target_y: Math.round(wy),
    });
  } else if (targetMode.type === 'probe') {
    send('flight_ops.deploy_probe', {
      target_x: Math.round(wx),
      target_y: Math.round(wy),
    });
  }

  exitTargetMode();
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

// Press Escape to cancel target-select
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && targetMode) exitTargetMode();
});

// ---------------------------------------------------------------------------
// Target-select mode helpers
// ---------------------------------------------------------------------------

function enterDroneTargetMode(droneId) {
  targetMode = { type: 'drone', droneId };
  targetHint.textContent = `Click map to launch ${droneId}`;
  targetHint.style.display = '';
  mapPanelEl.classList.add('fo-map-panel--targeting');
  // Highlight drone card
  document.querySelectorAll('.fo-drone-card').forEach(el => {
    el.classList.toggle('fo-drone-card--targeting', el.dataset.droneId === droneId);
  });
  renderDroneCards();
}

function enterProbeTargetMode() {
  targetMode = { type: 'probe' };
  targetHint.textContent = 'Click map to deploy probe';
  targetHint.style.display = '';
  mapPanelEl.classList.add('fo-map-panel--targeting');
  probeModeEl.style.display = '';
  deployBtnEl.classList.add('fo-btn--active');
}

function exitTargetMode() {
  targetMode = null;
  targetHint.style.display = 'none';
  mapPanelEl.classList.remove('fo-map-panel--targeting');
  document.querySelectorAll('.fo-drone-card').forEach(el => el.classList.remove('fo-drone-card--targeting'));
  probeModeEl.style.display = 'none';
  deployBtnEl.classList.remove('fo-btn--active');
  renderDroneCards();
  renderMap();
}

// ---------------------------------------------------------------------------
// Drone cards
// ---------------------------------------------------------------------------

function renderDroneCards() {
  if (!foState) return;

  droneCardsEl.innerHTML = '';

  for (const drone of foState.drones) {
    const card = document.createElement('div');
    card.className = 'fo-drone-card';
    card.dataset.droneId = drone.id;
    if (targetMode?.type === 'drone' && targetMode.droneId === drone.id) {
      card.classList.add('fo-drone-card--targeting');
    }

    // Header row
    const header = document.createElement('div');
    header.className = 'fo-drone-card__header';

    const idSpan = document.createElement('span');
    idSpan.className = 'fo-drone-id';
    idSpan.textContent = drone.id.toUpperCase();

    const badge = document.createElement('span');
    badge.className = `fo-drone-state-badge fo-drone-state-badge--${drone.state}`;
    badge.textContent = drone.state.toUpperCase();

    header.appendChild(idSpan);
    header.appendChild(badge);
    card.appendChild(header);

    // Fuel bar
    const fuelRow = document.createElement('div');
    fuelRow.className = 'fo-drone-card__fuel';

    const fuelLabel = document.createElement('span');
    fuelLabel.className = 'fo-fuel-label text-label';
    fuelLabel.textContent = 'FUEL';

    const barWrap = document.createElement('div');
    barWrap.className = 'fo-fuel-bar-wrap';

    const barFill = document.createElement('div');
    barFill.className = 'fo-fuel-bar-fill' + (drone.fuel <= DRONE_FUEL_LOW ? ' fo-fuel-bar-fill--low' : '');
    barFill.style.width = `${drone.fuel}%`;

    barWrap.appendChild(barFill);

    const pct = document.createElement('span');
    pct.className = 'fo-fuel-pct text-data';
    pct.textContent = `${Math.round(drone.fuel)}%`;

    fuelRow.appendChild(fuelLabel);
    fuelRow.appendChild(barWrap);
    fuelRow.appendChild(pct);
    card.appendChild(fuelRow);

    // Buttons
    const btns = document.createElement('div');
    btns.className = 'fo-drone-card__btns';

    if (drone.state === 'hangar') {
      const launchBtn = document.createElement('button');
      launchBtn.className = 'fo-btn';
      const isTargeting = targetMode?.type === 'drone' && targetMode.droneId === drone.id;
      if (isTargeting) {
        launchBtn.className += ' fo-btn--active';
        launchBtn.textContent = 'Cancel';
        launchBtn.addEventListener('click', () => exitTargetMode());
      } else {
        launchBtn.textContent = 'Launch';
        launchBtn.addEventListener('click', () => {
          if (targetMode) exitTargetMode();
          enterDroneTargetMode(drone.id);
        });
      }
      btns.appendChild(launchBtn);
    } else if (drone.state === 'transit' || drone.state === 'deployed') {
      const recallBtn = document.createElement('button');
      recallBtn.className = 'fo-btn fo-btn--warn';
      recallBtn.textContent = 'Recall';
      recallBtn.addEventListener('click', () => {
        if (targetMode?.droneId === drone.id) exitTargetMode();
        send('flight_ops.recall_drone', { drone_id: drone.id });
      });
      btns.appendChild(recallBtn);
    } else {
      // returning — no action available
      const retSpan = document.createElement('span');
      retSpan.className = 'text-dim text-label';
      retSpan.style.fontSize = '0.6rem';
      retSpan.textContent = 'RETURNING…';
      btns.appendChild(retSpan);
    }

    card.appendChild(btns);
    droneCardsEl.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// Probe panel
// ---------------------------------------------------------------------------

function renderProbePanel() {
  if (!foState) return;

  probeStockEl.textContent = `STOCK: ${foState.probe_stock}`;
  deployBtnEl.disabled = foState.probe_stock <= 0;

  if (foState.probes.length === 0) {
    probeListEl.innerHTML = '<p class="text-dim fo-no-probes">No probes deployed.</p>';
    return;
  }

  probeListEl.innerHTML = '';
  for (const p of foState.probes) {
    const row = document.createElement('div');
    row.className = 'fo-probe-row';

    const idSpan = document.createElement('span');
    idSpan.className = 'fo-probe-id';
    idSpan.textContent = p.id.toUpperCase();

    const coords = document.createElement('span');
    coords.className = 'fo-probe-coords';
    coords.textContent = `(${Math.round(p.x)}, ${Math.round(p.y)})`;

    row.appendChild(idSpan);
    row.appendChild(coords);
    probeListEl.appendChild(row);
  }
}

// ---------------------------------------------------------------------------
// Deploy probe button
// ---------------------------------------------------------------------------

deployBtnEl.addEventListener('click', () => {
  if (!foState || foState.probe_stock <= 0) return;
  if (targetMode?.type === 'probe') {
    exitTargetMode();
  } else {
    if (targetMode) exitTargetMode();
    enterProbeTargetMode();
  }
});
