/**
 * Starbridge — Science Station
 *
 * Long-range sensor display, contact selection, and active scan interface.
 * Canvas is North-up — ship at centre with actual heading shown on chevron.
 *
 * Server messages received:
 *   game.started             — show science UI, init canvas; payload includes
 *                              optional signal_location for Mission 3
 *   ship.state               — position, heading, sensor system state
 *   sensor.contacts          — range-filtered, scan-state-aware contact list
 *   science.scan_progress    — { entity_id, progress } — updates progress bar
 *   science.scan_complete    — { entity_id, results }  — shows results panel
 *   mission.signal_bearing   — { bearing, scan_count, ship_x, ship_y } —
 *                              triangulation bearing line from a scan position
 *   ship.hull_hit            — hit-flash border
 *   game.over                — defeat/victory overlay
 *
 * Server messages sent:
 *   lobby.claim_role         { role: 'science', player_name }
 *   science.start_scan       { entity_id }
 *   science.cancel_scan      {}
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import { setStatusDot, setAlertLevel, showBriefing, showGameOver } from '../shared/ui_components.js';
import { initPuzzleRenderer } from '../shared/puzzle_renderer.js';
import { SoundBank } from '../shared/audio.js';
import '../shared/audio_ambient.js';
import '../shared/audio_events.js';
import { wireButtonSounds } from '../shared/audio_ui.js';
import { registerHelp, initHelpOverlay } from '../shared/help_overlay.js';
import { initNotifications } from '../shared/notifications.js';
import { initRoleBar } from '../shared/role_bar.js';

registerHelp([
  { selector: '#sensor-canvas',     text: 'Sensor display — contacts shown within detection range.', position: 'right' },
  { selector: '#contact-list',      text: 'Contact list — click a contact to select it for scanning.', position: 'right' },
  { selector: '#scan-btn',          text: 'Initiate active scan — detailed readout on target\'s hull, shields, weakness.', position: 'left' },
  { selector: '#cancel-btn',        text: 'Cancel scan in progress.', position: 'left' },
]);
import { C_PRIMARY } from '../shared/renderer.js';
import { MapRenderer } from '../shared/map_renderer.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BASE_SENSOR_RANGE = 30_000;  // world units; must match server sensors.py
const HIT_FLASH_MS      = 500;

// Contact rendering sizes (half-size in pixels at max sensor zoom)
const CONTACT_SHAPES = {
  scout:     8,
  cruiser:   10,
  destroyer: 13,
};

const C_UNKNOWN  = '#ffff00';   // unknown contacts — yellow
const C_SCANNED  = C_PRIMARY;   // scanned contacts — green
const C_SELECTED = '#00aaff';   // selected contact glow — blue
const C_BEARING  = 'rgba(255, 176, 0, 0.55)'; // triangulation bearing lines — amber

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusDotEl    = document.querySelector('[data-status-dot]');
const statusLabelEl  = document.querySelector('[data-status-label]');
const standbyEl      = document.querySelector('[data-standby]');
const scienceMainEl  = document.querySelector('[data-science-main]');
const missionLabelEl = document.getElementById('mission-label');
const stationEl      = document.querySelector('.station-container');

const sensorCanvas     = document.getElementById('sensor-canvas');
const sensorRangeLabel = document.getElementById('sensor-range-label');

const contactListEl  = document.getElementById('contact-list');
const contactCountEl = document.getElementById('contact-count');

const scanTargetLabel  = document.getElementById('scan-target-label');
const scanProgressFill = document.getElementById('scan-progress-fill');
const scanProgressPct  = document.getElementById('scan-progress-pct');
const scanBtn          = document.getElementById('scan-btn');
const cancelBtn        = document.getElementById('cancel-btn');

const resultsSectionEl   = document.getElementById('results-section');
const resultsEntityLabel = document.getElementById('results-entity-label');
const resType            = document.getElementById('res-type');
const resHullFill        = document.getElementById('res-hull-fill');
const resHullPct         = document.getElementById('res-hull-pct');
const resShieldFwdFill   = document.getElementById('res-shield-fwd-fill');
const resShieldFwdPct    = document.getElementById('res-shield-fwd-pct');
const resShieldAftFill   = document.getElementById('res-shield-aft-fill');
const resShieldAftPct    = document.getElementById('res-shield-aft-pct');
const resWeaknessRow     = document.getElementById('res-weakness-row');
const resWeakness        = document.getElementById('res-weakness');

const sensorPowerEl = document.getElementById('sensor-power');
const sensorEffEl   = document.getElementById('sensor-efficiency');

// ---------------------------------------------------------------------------
// Game state
// ---------------------------------------------------------------------------

let gameActive     = false;
let sensorRenderer = null;

let shipState   = null;               // most recent ship.state payload
let contacts    = [];                 // most recent sensor.contacts list
let selectedId  = null;              // selected contact entity_id or null
let scanningId  = null;               // entity_id currently being scanned
let sensorRange = BASE_SENSOR_RANGE;  // updated from ship.state

// Mission 3 — triangulation state
let signalLocation = null;           // {x, y} from game.started payload, or null
let bearingLines   = [];             // [{bearing, ship_x, ship_y}] from mission.signal_bearing
let signalScanCount = 0;             // 0, 1, or 2 — how many bearing scans recorded

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();

    // Re-claim role so this connection receives role-filtered sensor.contacts.
    if (status === 'connected') {
      const name = sessionStorage.getItem('player_name') || 'SCIENCE';
      send('lobby.claim_role', { role: 'science', player_name: name });
    }
  });

  on('game.started',             handleGameStarted);
  on('ship.state',               handleShipState);
  on('ship.alert_changed',       ({ level }) => setAlertLevel(level));
  on('sensor.contacts',          handleSensorContacts);
  on('science.scan_progress',    handleScanProgress);
  on('science.scan_complete',    handleScanComplete);
  on('mission.signal_bearing',   handleSignalBearing);
  on('ship.hull_hit',            handleHullHit);
  on('game.over',                handleGameOver);

  initPuzzleRenderer(send);
  setupControls();
  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();
  initNotifications(send, 'science');
  initRoleBar(send, 'science');
  connect();
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function handleGameStarted(payload) {
  missionLabelEl.textContent  = payload.mission_name.toUpperCase();
  standbyEl.style.display     = 'none';
  scienceMainEl.style.display = 'grid';
  gameActive = true;

  // Reset triangulation state for new game.
  signalLocation  = payload.signal_location || null;
  bearingLines    = [];
  signalScanCount = 0;

  requestAnimationFrame(() => {
    sensorRenderer = new MapRenderer(sensorCanvas, {
      range:         sensorRange,
      orientation:   'north-up',
      showGrid:      false,
      showRangeRings: true,
      interactive:   true,
      drawContact:   (ctx, sx, sy, contact, selected, _now) => {
        if (contact.scan_state === 'scanned') {
          drawScannedContact(ctx, sx, sy, contact.type, selected);
        } else {
          drawUnknownContact(ctx, sx, sy, selected);
        }
      },
    });
    sensorRenderer.onContactClick((id) => selectContact(id));
    requestAnimationFrame(renderLoop);
  });

  // If this mission has a signal, inject a pseudo-contact so Science can scan it.
  if (signalLocation) {
    renderContactList();
    updateScanUI();
  }

  if (payload.briefing_text) {
    showBriefing(payload.mission_name, payload.briefing_text);
  }

  console.log(`[science] Game started — mission: ${payload.mission_id}`);
  SoundBank.setAmbient('sensor_sweep', { active: true });
}

function handleShipState(payload) {
  if (!gameActive) return;
  shipState = payload;

  // Derive sensor range from sensor system efficiency.
  const sensorEff = payload.systems?.sensors?.efficiency ?? 1.0;
  sensorRange     = BASE_SENSOR_RANGE * sensorEff;

  if (sensorRenderer) {
    sensorRenderer._range = sensorRange;
    sensorRenderer.updateShipState(payload);
  }

  // Update sensor status panel.
  const power = payload.systems?.sensors?.power ?? 0;
  sensorPowerEl.textContent = `${Math.round(power)}%`;
  sensorEffEl.textContent   = `${Math.round(sensorEff * 100)}%`;

  // Update range label in panel header.
  sensorRangeLabel.textContent = `RANGE: ${(sensorRange / 1000).toFixed(0)}km`;
}

function handleSensorContacts(payload) {
  if (!gameActive) return;
  contacts = payload.contacts || [];

  // If selected or scanning target is no longer in contacts, clear it.
  const ids = new Set(contacts.map(c => c.id));
  if (selectedId && !ids.has(selectedId)) {
    selectedId = null;
  }
  if (scanningId && !ids.has(scanningId)) {
    scanningId = null;
    resetScanProgress();
  }

  if (sensorRenderer) sensorRenderer.updateContacts(contacts);

  renderContactList();
  updateScanUI();
}

function handleScanProgress(payload) {
  if (!gameActive) return;
  // Signal scans are instant — progress updates only apply to real entity scans.
  if (payload.entity_id === 'signal') return;
  scanningId = payload.entity_id;

  const pct = Math.min(100, Math.max(0, payload.progress));
  scanProgressFill.style.width = `${pct}%`;
  scanProgressPct.textContent  = `${Math.round(pct)}%`;
  cancelBtn.disabled           = false;
  scanTargetLabel.textContent  = `SCANNING: ${payload.entity_id.toUpperCase()}`;
}

function handleScanComplete(payload) {
  if (!gameActive) return;
  SoundBank.play('scan_complete');
  scanningId = null;
  resetScanProgress();

  const r = payload.results;
  if (!r) return;

  resultsSectionEl.style.display = '';
  resultsEntityLabel.textContent = payload.entity_id.toUpperCase();
  resType.textContent            = (r.type || '—').toUpperCase();

  const hullPct = r.hull_max > 0 ? (r.hull / r.hull_max) * 100 : 0;
  resHullFill.style.width      = `${Math.max(0, hullPct)}%`;
  resHullPct.textContent       = `${Math.round(r.hull)}`;

  resShieldFwdFill.style.width = `${Math.max(0, r.shield_front)}%`;
  resShieldFwdPct.textContent  = `${Math.round(r.shield_front)}`;
  resShieldAftFill.style.width = `${Math.max(0, r.shield_rear)}%`;
  resShieldAftPct.textContent  = `${Math.round(r.shield_rear)}`;

  if (r.weakness) {
    resWeaknessRow.style.display = '';
    resWeakness.textContent      = r.weakness;
  } else {
    resWeaknessRow.style.display = 'none';
  }

  console.log(`[science] Scan complete: ${payload.entity_id}`);
}

function handleSignalBearing(payload) {
  if (!gameActive) return;
  bearingLines.push({ bearing: payload.bearing, ship_x: payload.ship_x, ship_y: payload.ship_y });
  signalScanCount = payload.scan_count;

  // Update the signal contact row to reflect updated scan count.
  renderContactList();

  // Show a bearing readout under the scan progress bar.
  const bearingStr = `BEARING ${payload.bearing.toFixed(1)}°`;
  const countStr   = signalScanCount >= 2
    ? 'TRIANGULATED'
    : `SCAN ${signalScanCount}/2 COMPLETE`;
  scanTargetLabel.textContent = `${bearingStr} — ${countStr}`;

  console.log(`[science] Signal bearing: ${payload.bearing}° (scan ${payload.scan_count}/2)`);
}

function handleHullHit() {
  if (!gameActive) return;
  SoundBank.play('hull_hit');
  stationEl.classList.add('hit');
  setTimeout(() => stationEl.classList.remove('hit'), HIT_FLASH_MS);
}

function handleGameOver(payload) {
  gameActive = false;
  SoundBank.play(payload.result === 'victory' ? 'victory' : 'defeat');
  SoundBank.stopAmbient('sensor_sweep');
  showGameOver(payload.result, payload.stats || {});
}

// ---------------------------------------------------------------------------
// Control setup
// ---------------------------------------------------------------------------

function setupControls() {
  scanBtn.addEventListener('click', () => {
    if (!gameActive || !selectedId) return;
    send('science.start_scan', { entity_id: selectedId });
    if (selectedId === 'signal') {
      // Signal scan is instant — server replies with mission.signal_bearing, no progress.
      // Don't set scanningId; just disable briefly to prevent rapid double-tap.
      scanBtn.disabled = true;
      setTimeout(() => { if (gameActive) { scanBtn.disabled = false; } }, 800);
    } else {
      scanningId = selectedId;
      scanTargetLabel.textContent = `SCANNING: ${selectedId.toUpperCase()}`;
      scanBtn.disabled  = true;
      cancelBtn.disabled = false;
    }
  });

  cancelBtn.addEventListener('click', () => {
    if (!gameActive) return;
    send('science.cancel_scan', {});
    scanningId = null;
    resetScanProgress();
  });
}

function selectContact(id) {
  selectedId = id;
  if (sensorRenderer) sensorRenderer.selectContact(id);
  renderContactList();
  updateScanUI();
}

// ---------------------------------------------------------------------------
// UI updates
// ---------------------------------------------------------------------------

function renderContactList() {
  // Build display list: real contacts + optional signal pseudo-contact.
  const displayContacts = [...contacts];
  if (signalLocation && signalScanCount < 2) {
    displayContacts.unshift({
      id: 'signal',
      x: signalLocation.x,
      y: signalLocation.y,
      type: 'signal',
      scan_state: 'unknown',
      _isSignal: true,
    });
  }

  if (displayContacts.length === 0) {
    contactCountEl.textContent = '—';
    contactListEl.innerHTML = '<p class="text-dim contact-list__empty">No contacts detected.</p>';
    return;
  }

  contactCountEl.textContent = `${displayContacts.length}`;
  contactListEl.innerHTML = '';

  for (const c of displayContacts) {
    const row = document.createElement('div');
    row.className = 'contact-row' + (c.id === selectedId ? ' contact-row--selected' : '');

    let rangeStr = '—';
    if (shipState && c._isSignal) {
      // Signal range is approximate (≈ direction, distance unknown until triangulated).
      rangeStr = 'UNKNOWN';
    } else if (shipState) {
      const dx   = c.x - shipState.position.x;
      const dy   = c.y - shipState.position.y;
      const dist = Math.hypot(dx, dy);
      rangeStr   = `${(dist / 1000).toFixed(1)}km`;
    }

    let badgeClass, badgeText;
    if (c._isSignal) {
      const scansDone = signalScanCount;
      badgeClass = scansDone > 0
        ? 'contact-scan-badge contact-scan-badge--scanned'
        : 'contact-scan-badge contact-scan-badge--unknown';
      badgeText = scansDone > 0 ? `${scansDone}/2` : 'SIG';
    } else {
      badgeClass = c.scan_state === 'scanned'
        ? 'contact-scan-badge contact-scan-badge--scanned'
        : 'contact-scan-badge contact-scan-badge--unknown';
      badgeText = c.scan_state === 'scanned' ? 'SCND' : 'UNK';
    }

    row.innerHTML = `
      <span class="contact-row__id">${c.id.toUpperCase()}</span>
      <span class="contact-row__range">${rangeStr}</span>
      <span class="${badgeClass}">${badgeText}</span>
    `;

    row.addEventListener('click', () => selectContact(c.id));
    contactListEl.appendChild(row);
  }
}

function updateScanUI() {
  // Check real contacts first; then signal pseudo-contact.
  const target = contacts.find(c => c.id === selectedId)
    ?? (selectedId === 'signal' && signalLocation ? { id: 'signal', _isSignal: true } : null);

  if (!target) {
    if (!scanningId) {
      scanTargetLabel.textContent = 'No target selected';
    }
    scanBtn.disabled = true;
    return;
  }

  if (target._isSignal) {
    const remaining = 2 - signalScanCount;
    scanTargetLabel.textContent = remaining > 0
      ? `SIGNAL — ${remaining} SCAN${remaining > 1 ? 'S' : ''} REMAINING`
      : 'SIGNAL — TRIANGULATED';
    // Allow re-scanning even after 2 scans (ship may have moved for better fix).
    scanBtn.disabled = (scanningId !== null);
    return;
  }

  scanTargetLabel.textContent = `TARGET: ${target.id.toUpperCase()}`;
  // Allow re-scan even if already scanned (e.g. to refresh results).
  scanBtn.disabled = (scanningId !== null);
}

function resetScanProgress() {
  scanProgressFill.style.width = '0%';
  scanProgressPct.textContent  = '0%';
  cancelBtn.disabled           = true;

  if (selectedId) {
    scanTargetLabel.textContent = `TARGET: ${selectedId.toUpperCase()}`;
    scanBtn.disabled = false;
  } else {
    scanTargetLabel.textContent = 'No target selected';
    scanBtn.disabled = true;
  }
}

// ---------------------------------------------------------------------------
// Render loop
// ---------------------------------------------------------------------------

function renderLoop(now) {
  if (!gameActive) return;

  sensorRenderer.render(now);

  // Science-specific overlay: triangulation bearing lines drawn on top.
  if (bearingLines.length > 0) {
    const ctx = sensorCanvas.getContext('2d');
    drawBearingLines(ctx, sensorCanvas.width, sensorCanvas.height);
  }

  requestAnimationFrame(renderLoop);
}

// ---------------------------------------------------------------------------
// Contact drawing (station-specific, NOT in renderer.js)
// ---------------------------------------------------------------------------

function drawUnknownContact(ctx, sx, sy, selected) {
  ctx.save();
  ctx.translate(sx, sy);

  // Filled dot.
  ctx.fillStyle = selected ? C_SELECTED : C_UNKNOWN;
  ctx.beginPath();
  ctx.arc(0, 0, 4, 0, Math.PI * 2);
  ctx.fill();

  // Outer ping ring.
  ctx.strokeStyle = selected
    ? 'rgba(0, 170, 255, 0.5)'
    : 'rgba(255, 255, 0, 0.3)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(0, 0, selected ? 12 : 9, 0, Math.PI * 2);
  ctx.stroke();

  ctx.restore();
}

function drawScannedContact(ctx, sx, sy, type, selected) {
  const halfSize = CONTACT_SHAPES[type] ?? CONTACT_SHAPES.cruiser;

  ctx.save();
  ctx.translate(sx, sy);
  ctx.strokeStyle = selected ? C_SELECTED : C_SCANNED;
  ctx.lineWidth   = selected ? 2 : 1.5;

  if (type === 'scout') {
    // Diamond
    ctx.beginPath();
    ctx.moveTo(0, -halfSize);
    ctx.lineTo(halfSize, 0);
    ctx.lineTo(0, halfSize);
    ctx.lineTo(-halfSize, 0);
    ctx.closePath();
    ctx.stroke();
  } else if (type === 'cruiser') {
    // Equilateral triangle
    ctx.beginPath();
    ctx.moveTo(0, -halfSize);
    ctx.lineTo(halfSize * 0.866, halfSize * 0.5);
    ctx.lineTo(-halfSize * 0.866, halfSize * 0.5);
    ctx.closePath();
    ctx.stroke();
  } else {
    // Hexagon (destroyer + any unknown type)
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = (i * Math.PI) / 3 - Math.PI / 6;
      if (i === 0) ctx.moveTo(Math.cos(a) * halfSize, Math.sin(a) * halfSize);
      else         ctx.lineTo(Math.cos(a) * halfSize, Math.sin(a) * halfSize);
    }
    ctx.closePath();
    ctx.stroke();
  }

  // Selected glow ring.
  if (selected) {
    ctx.strokeStyle = C_SELECTED;
    ctx.lineWidth   = 1;
    ctx.beginPath();
    ctx.arc(0, 0, halfSize + 7, 0, Math.PI * 2);
    ctx.stroke();
  }

  ctx.restore();
}

// ---------------------------------------------------------------------------
// Triangulation bearing line rendering
// ---------------------------------------------------------------------------

/**
 * Draw bearing lines from each scan position outward across the canvas.
 * Each line starts at the scan ship position (plotted in world coords) and
 * extends in the bearing direction to the canvas edge.
 *
 * If 2 bearings exist and a signal_location is known, also draw a cross-hair
 * at the estimated intersection.
 */
function drawBearingLines(ctx, cw, ch) {
  ctx.save();

  for (const { bearing, ship_x, ship_y } of bearingLines) {
    // Map the scan ship position to canvas coords via MapRenderer.
    const origin = sensorRenderer.worldToCanvas(ship_x, ship_y);

    // Bearing is degrees CW from North. Convert to canvas angle (North-up, y-down).
    const rad = (bearing * Math.PI) / 180;
    // Direction vector: sin(bearing)→x, -cos(bearing)→y (North-up convention).
    const dx = Math.sin(rad);
    const dy = -Math.cos(rad);

    // Extend to well beyond canvas bounds.
    const tMax = Math.max(cw, ch) * 3;

    ctx.strokeStyle = C_BEARING;
    ctx.lineWidth   = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(origin.x, origin.y);
    ctx.lineTo(origin.x + dx * tMax, origin.y + dy * tMax);
    ctx.stroke();
    ctx.setLineDash([]);

    // Small dot at the scan origin position.
    ctx.fillStyle = C_BEARING;
    ctx.beginPath();
    ctx.arc(origin.x, origin.y, 3, 0, Math.PI * 2);
    ctx.fill();

    // Bearing label near origin.
    ctx.fillStyle    = C_BEARING;
    ctx.font         = '9px "Share Tech Mono", monospace';
    ctx.textAlign    = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(`BRG ${bearing.toFixed(1)}°`, origin.x + 6, origin.y + 2);
  }

  // If triangulated, draw a pulsing cross-hair at the signal location.
  if (bearingLines.length >= 2 && signalLocation) {
    const sp = sensorRenderer.worldToCanvas(signalLocation.x, signalLocation.y);
    const R = 10;
    ctx.strokeStyle = C_BEARING;
    ctx.lineWidth   = 1.5;
    ctx.beginPath();
    ctx.moveTo(sp.x - R, sp.y); ctx.lineTo(sp.x + R, sp.y);
    ctx.moveTo(sp.x, sp.y - R); ctx.lineTo(sp.x, sp.y + R);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, R * 1.5, 0, Math.PI * 2);
    ctx.stroke();

    ctx.fillStyle    = C_BEARING;
    ctx.font         = '9px "Share Tech Mono", monospace';
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText('SIGNAL', sp.x, sp.y - R * 1.5 - 3);
  }

  ctx.restore();
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
