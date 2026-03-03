/**
 * Starbridge — Helm Station
 *
 * Controls:
 *   A / ←   — Turn left  (5° per step)
 *   D / →   — Turn right (5° per step)
 *   W / ↑   — Throttle up   (5% per step)
 *   S / ↓   — Throttle down (5% per step)
 *   Click compass  — Set target heading
 *   Throttle slider — Set throttle directly
 *
 * Interpolation:
 *   The server ticks at 10 Hz. We store the previous and current server
 *   state and lerp between them based on time since the last tick, giving
 *   smooth 60 fps motion without waiting for the next server update.
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
import { initCrewRoster } from '../shared/crew_roster.js';
import { SectorMap } from '../shared/sector_map.js';
import { RangeControl, STATION_RANGES } from '../shared/range_control.js';
import { MapRenderer } from '../shared/map_renderer.js';

registerHelp([
  { selector: '#compass',          text: 'Heading dial — click to set target heading. Ship turns toward it.', position: 'right' },
  { selector: '#throttle-slider',  text: 'Throttle — ship speed 0–100%. W/S or ↑↓ to adjust.', position: 'right' },
  { selector: '#minimap',          text: 'Sector minimap — green chevron = you, red = enemies.', position: 'left' },
  { selector: '#viewscreen',       text: 'Navigation map — Z to cycle zoom (tactical/sector/strategic).', position: 'below' },
]);
import {
  lerp,
  lerpAngle,
  drawCompass,
  drawMinimap,
  drawShipChevron,
} from '../shared/renderer.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TICK_MS        = 100;    // server tick interval — must match game_loop.py
const HEADING_STEP   = 5;      // degrees per key press
const THROTTLE_STEP  = 5;      // % per key press
const HIT_FLASH_MS   = 400;
const BEAM_FLASH_MS  = 300;

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusDotEl   = document.querySelector('[data-status-dot]');
const statusLabelEl = document.querySelector('[data-status-label]');
const standbyEl     = document.querySelector('[data-standby]');
const helmMainEl    = document.querySelector('[data-helm-main]');
const missionLabelEl = document.getElementById('mission-label');

const viewscreenCanvas  = document.getElementById('viewscreen');
const compassCanvas     = document.getElementById('compass');
const minimapCanvas     = document.getElementById('minimap');

const targetHdgDisplay  = document.getElementById('target-heading-display');
const throttleSlider    = document.getElementById('throttle-slider');
const throttleDisplay   = document.getElementById('throttle-display');
const throttleGaugeFill = document.getElementById('throttle-gauge-fill');
const speedBadge        = document.getElementById('speed-badge');

const telemHeading  = document.getElementById('telem-heading');
const telemSpeed    = document.getElementById('telem-speed');
const telemThrottle = document.getElementById('telem-throttle');
const telemPosX     = document.getElementById('telem-pos-x');
const telemPosY     = document.getElementById('telem-pos-y');

// ---------------------------------------------------------------------------
// Game state
// ---------------------------------------------------------------------------

// Enemy contacts from world.entities (for minimap overlay).
let contacts = [];
// Hazard zones from world.entities.
let hazards = [];
// Beam flash: { targetX, targetY, startTime } — shown on minimap
let beamFlash = null;

let gameActive    = false;
let hintsEnabled  = false;  // true when difficulty === 'cadet'

/**
 * Server-provided ship state snapshots.
 * prevState: the state before the most recent tick.
 * currState: the most recent tick state.
 * lastTickTime: performance.now() when currState arrived.
 */
const DEFAULT_STATE = {
  heading:  0,
  velocity: 0,
  throttle: 0,
  position: { x: 50_000, y: 50_000 },
};

let prevState    = null;
let currState    = null;
let lastTickTime = 0;

/** Player's commanded values (local authority — sent to server immediately). */
let targetHeading = 0;
let throttle      = 0;

// Held-key tracking for smooth repeat (processed in the rAF loop).
const heldKeys = new Set();
let   lastControlSend = 0;

// Canvas contexts (obtained after game start when canvases are visible).
let cmpCtx = null; // compass
let mmCtx  = null; // minimap

// Navigation map renderer (viewscreen canvas).
let _mapRenderer     = null;
let _rangeControl    = null;

// Sector map (handles zoom levels: tactical/sector/strategic).
let _sectorMap       = null;
let _routeData       = null;   // current route from map.route_updated
let _stationEntities = [];     // station entities from map.sector_grid (v0.05e)

// Science sector-scan status indicator (shown on minimap).
let _scanIndicatorText = null;

// Docking state (v0.05f).
let _dockedAt      = null;   // station ID if docked, null otherwise
let _approachInfo  = null;   // latest docking.approach_info payload

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();
  });

  // C.1.2: ALL STOP acknowledge button.
  const _allStopAckBtn = document.getElementById('all-stop-ack-btn');
  if (_allStopAckBtn) {
    _allStopAckBtn.addEventListener('click', () => send('captain.acknowledge_all_stop', {}));
  }

  on('lobby.welcome',      handleWelcome);
  on('game.started',       handleGameStarted);
  on('ship.state',         handleShipState);
  on('world.entities',     handleWorldEntities);
  on('ship.alert_changed', ({ level }) => { setAlertLevel(level); SoundBank.setAmbient('alert_level', { level }); });
  on('ship.hull_hit',      handleHullHit);
  on('weapons.beam_fired', handleBeamFired);
  on('game.over',          handleGameOver);
  on('map.sector_grid',    (p) => {
    if (_sectorMap) _sectorMap.updateSectorGrid(p);
    _routeData = p.route || null;
    _stationEntities = p.station_entities || [];
    // Update range control with sector bounds for SEC auto-calc.
    if (_rangeControl && p.sectors) {
      for (const s of Object.values(p.sectors)) {
        if (s.visibility === 'active') {
          const [col, row] = s.grid_position;
          const SECTOR_SIZE = 100_000;
          _rangeControl.setSectorBounds(
            (col + 0.5) * SECTOR_SIZE, (row + 0.5) * SECTOR_SIZE, SECTOR_SIZE,
          );
          break;
        }
      }
      _rangeControl.setStrategicGrid(p);
    }
  });
  on('map.scan_indicator', ({ text }) => { _scanIndicatorText = text || null; });
  on('docking.approach_info', (info) => { _approachInfo = info; });
  on('docking.complete',      ({ station_name }) => { _approachInfo = null; console.log('[helm] Docked at', station_name); });
  on('docking.undocked',      () => { _dockedAt = null; });
  on('comms.contacts',        (p) => { if (_mapRenderer) _mapRenderer.updateCommsContacts(p.contacts || []); });

  initPuzzleRenderer(send);
  setupKeyboard();
  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();
  initNotifications(send, 'helm');
  initRoleBar(send, 'helm');
  initCrewRoster(send);
  connect();
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function handleWelcome(payload) {
  console.log('[helm] Connected as', payload.connection_id);
  // Re-claim role so this connection receives world.entities broadcasts.
  const name = sessionStorage.getItem('player_name') || 'HELM';
  send('lobby.claim_role', { role: 'helm', player_name: name });
}

function handleGameStarted(payload) {
  missionLabelEl.textContent = payload.mission_name.toUpperCase();
  standbyEl.style.display    = 'none';
  helmMainEl.style.display   = 'grid';
  gameActive = true;

  // Range control (replaces old fixed NAV_MAP_RANGE + SectorMap zoom).
  const helmRanges = STATION_RANGES.helm;
  _rangeControl = new RangeControl({
    container:    document.getElementById('range-bar'),
    stationId:    'helm',
    ranges:       helmRanges.available,
    defaultRange: helmRanges.default,
    onChange:      _onHelmRangeChange,
  });
  _rangeControl.attach();

  // Navigation map on the viewscreen canvas.
  if (viewscreenCanvas) {
    _mapRenderer = new MapRenderer(viewscreenCanvas, {
      range:          _rangeControl.currentRangeUnits(),
      orientation:    'north-up',
      showGrid:       true,
      showRangeRings: true,
      zoom:           { enabled: true },
    });
  }

  // Sector map for strategic grid + sector boundary overlays.
  _sectorMap = new SectorMap({
    allowedLevels: ['tactical', 'sector', 'strategic'],
    defaultZoom:   'tactical',
    onRoutePlot:   (wx, wy) => send('map.plot_route', { to_x: wx, to_y: wy }),
    onZoomChange:  () => {},
  });
  if (_mapRenderer) _sectorMap.setMapRenderer(_mapRenderer);
  if (minimapCanvas) _sectorMap.setupStrategicClick(minimapCanvas);
  if (viewscreenCanvas) _sectorMap.setupStrategicClick(viewscreenCanvas);

  // Defer canvas setup to the next frame so the grid layout is fully
  // computed before we read clientWidth/clientHeight for sizing.
  requestAnimationFrame(() => {
    cmpCtx = compassCanvas.getContext('2d');
    mmCtx  = minimapCanvas.getContext('2d');

    requestAnimationFrame(renderLoop);
  });

  if (payload.briefing_text) {
    showBriefing(payload.mission_name, payload.briefing_text);
  }

  hintsEnabled = payload.difficulty === 'cadet';
  console.log(`[helm] Game started — mission: ${payload.mission_id}`);
  SoundBank.setAmbient('life_support', { active: true });
  SoundBank.setAmbient('engine_hum', { throttle: 0, enginePower: 1 });
}

function handleShipState(payload) {
  if (!gameActive) return;
  prevState    = currState;
  currState    = payload;
  lastTickTime = performance.now();
  _dockedAt = payload.docked_at ?? null;
  // Clear approach info once docked — it's no longer relevant.
  if (_dockedAt) _approachInfo = null;
  SoundBank.setAmbient('engine_hum', { throttle: payload.throttle ?? 0, enginePower: payload.systems?.engines?.efficiency ?? 1 });
  if (_mapRenderer) _mapRenderer.updateShipState(payload);
  if (_sectorMap && payload.position) {
    _sectorMap.updateShipPosition(payload.position.x, payload.position.y, payload.heading ?? 0);
  }
  // C.1.2: ALL STOP overlay
  _updateAllStopOverlay(payload.all_stop_active ?? false);
}

function _updateAllStopOverlay(active) {
  const overlay = document.getElementById('all-stop-overlay');
  if (!overlay) return;
  overlay.style.display = active ? 'flex' : 'none';
}

function handleWorldEntities(payload) {
  if (!gameActive) return;
  contacts = payload.enemies  || [];
  hazards  = payload.hazards  || [];
  if (_mapRenderer) {
    _mapRenderer.updateContacts(payload.enemies || [], payload.torpedoes || []);
    _mapRenderer.updateHazards(payload.hazards || []);
  }
}

function handleHullHit() {
  if (!gameActive) return;
  SoundBank.play('hull_hit');
  const el = document.querySelector('.station-container');
  if (el) {
    el.classList.add('hit');
    setTimeout(() => el.classList.remove('hit'), HIT_FLASH_MS);
  }
}

function handleBeamFired(payload) {
  if (!gameActive) return;
  beamFlash = { targetX: payload.target_x, targetY: payload.target_y, startTime: performance.now() };
}

function handleGameOver(payload) {
  gameActive = false;
  SoundBank.play(payload.result === 'victory' ? 'victory' : 'defeat');
  SoundBank.stopAmbient('engine_hum');
  SoundBank.stopAmbient('life_support');
  SoundBank.stopAmbient('alert_level');
  showGameOver(payload.result, payload.stats || {});
}

// ---------------------------------------------------------------------------
// Interpolation
// ---------------------------------------------------------------------------

/**
 * Return a ship state interpolated between prevState and currState based
 * on how far we are into the current tick period. Returns currState directly
 * if there is only one data point.
 */
function getInterpolatedState() {
  if (!currState) return DEFAULT_STATE;
  if (!prevState) return currState;

  const t = Math.min((performance.now() - lastTickTime) / TICK_MS, 1.0);
  return {
    heading:  lerpAngle(prevState.heading,    currState.heading,    t),
    velocity: lerp(prevState.velocity,        currState.velocity,   t),
    throttle: currState.throttle,
    position: {
      x: lerp(prevState.position.x, currState.position.x, t),
      y: lerp(prevState.position.y, currState.position.y, t),
    },
  };
}

// ---------------------------------------------------------------------------
// Render loop
// ---------------------------------------------------------------------------

function renderLoop(now) {
  if (!gameActive) return;

  processHeldKeys(now);

  const state = getInterpolatedState();
  if (state) {
    drawNavMap(now);
    drawCompassPanel(state);
    drawMinimapPanel(state);
    updateTelemetry(state);
  }

  requestAnimationFrame(renderLoop);
}

// ---------------------------------------------------------------------------
// Canvas draws
// ---------------------------------------------------------------------------

function drawNavMap(now) {
  if (_rangeControl && _rangeControl.isStrategic() && _sectorMap) {
    // Strategic zoom: render sector grid on the main canvas.
    _sectorMap.setZoomLevel('strategic');
    _sectorMap.renderStrategic(viewscreenCanvas, now);
  } else if (_mapRenderer) {
    _mapRenderer.render(now);
    // Station icons overlay.
    const ctx = viewscreenCanvas.getContext('2d');
    if (_sectorMap) {
      _sectorMap.renderStationOverlay(ctx, viewscreenCanvas, _mapRenderer);
    }
    // Sector boundary overlay in SEC mode.
    if (_rangeControl && _rangeControl.isSector() && _sectorMap) {
      _sectorMap.setZoomLevel('sector');
      _sectorMap.renderSectorBoundaryOverlay(ctx, viewscreenCanvas, _mapRenderer);
    }
  }
}

function drawCompassPanel(state) {
  const size = compassCanvas.width; // always square
  drawCompass(cmpCtx, size, state.heading, targetHeading);
}

function drawMinimapPanel(state) {
  const size = minimapCanvas.width;
  if (_rangeControl && _rangeControl.isStrategic() && _sectorMap) {
    // Strategic zoom: render the sector grid on the minimap canvas.
    _sectorMap.renderStrategic(minimapCanvas, performance.now());
    return;
  }
  // Tactical / sector zoom: standard minimap rendering.
  drawMinimap(mmCtx, size, state.position.x, state.position.y, state.heading);
  drawMinimapHazards(mmCtx, size);
  drawMinimapStations(mmCtx, size);
  drawMinimapContacts(mmCtx, size, state);
  drawMinimapBeamFlash(mmCtx, size, state);
  if (hintsEnabled) drawMinimapThreatArrow(mmCtx, size, state);
  // Sector zoom: draw the route overlay on the minimap.
  if (_rangeControl && _rangeControl.isSector() && _routeData?.plot_x) {
    _drawMinimapRoute(mmCtx, size, _routeData);
  }
  // Science scan indicator overlay.
  if (_scanIndicatorText) {
    mmCtx.save();
    mmCtx.font         = '8px "Share Tech Mono",monospace';
    mmCtx.textAlign    = 'left';
    mmCtx.textBaseline = 'bottom';
    mmCtx.fillStyle    = 'rgba(255,176,0,0.9)';
    mmCtx.fillText(_scanIndicatorText, 4, size - 3);
    mmCtx.restore();
  }
  // Docking state overlay.
  if (_dockedAt) {
    mmCtx.save();
    mmCtx.font         = '9px "Share Tech Mono",monospace';
    mmCtx.textAlign    = 'center';
    mmCtx.textBaseline = 'top';
    mmCtx.fillStyle    = 'rgba(0,200,255,0.9)';
    mmCtx.fillText('DOCKED', size / 2, 4);
    mmCtx.restore();
  } else if (_approachInfo && _approachInfo.in_range) {
    mmCtx.save();
    mmCtx.font         = '8px "Share Tech Mono",monospace';
    mmCtx.textAlign    = 'center';
    mmCtx.textBaseline = 'top';
    mmCtx.fillStyle    = 'rgba(0,255,160,0.9)';
    mmCtx.fillText('IN DOCK RANGE', size / 2, 4);
    mmCtx.restore();
  }
}

/**
 * Cadet hint: amber arrow on minimap edge pointing toward nearest enemy.
 */
function drawMinimapThreatArrow(ctx, size, state) {
  if (!contacts.length) return;

  // Find nearest enemy.
  let nearest = null, minDist = Infinity;
  for (const c of contacts) {
    const d = Math.hypot(c.x - state.position.x, c.y - state.position.y);
    if (d < minDist) { minDist = d; nearest = c; }
  }
  if (!nearest) return;

  const PAD    = 6;
  const SECTOR = 100_000;
  const mapW   = size - PAD * 2;

  // Player and target map positions.
  const px = PAD + (state.position.x / SECTOR) * mapW;
  const py = PAD + (state.position.y / SECTOR) * mapW;
  const tx = PAD + (nearest.x / SECTOR) * mapW;
  const ty = PAD + (nearest.y / SECTOR) * mapW;

  // Direction angle and arrow tip clamped to minimap edge.
  const angle = Math.atan2(ty - py, tx - px);
  const cx    = size / 2;
  const cy    = size / 2;
  const MARGIN = 12;
  const R      = cx - MARGIN;
  const tipX   = cx + Math.cos(angle) * R;
  const tipY   = cy + Math.sin(angle) * R;

  // Arrow size.
  const A = 8;
  const left  = angle + Math.PI * 0.8;
  const right = angle - Math.PI * 0.8;
  const alpha = 0.7 + 0.3 * Math.sin(performance.now() * 0.004);

  ctx.save();
  ctx.fillStyle = `rgba(255, 176, 0, ${alpha})`;
  ctx.beginPath();
  ctx.moveTo(tipX, tipY);
  ctx.lineTo(tipX + Math.cos(left)  * A, tipY + Math.sin(left)  * A);
  ctx.lineTo(tipX + Math.cos(right) * A, tipY + Math.sin(right) * A);
  ctx.closePath();
  ctx.fill();

  // Label below the arrow tip.
  ctx.fillStyle    = `rgba(255, 176, 0, ${alpha})`;
  ctx.font         = '10px "Share Tech Mono", monospace';
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'middle';
  const labelX = cx + Math.cos(angle) * (R + 10);
  const labelY = cy + Math.sin(angle) * (R + 10);
  // Only draw label if it fits inside canvas.
  if (labelX > 2 && labelX < size - 2 && labelY > 2 && labelY < size - 2) {
    ctx.fillText('THREAT', labelX, labelY);
  }
  ctx.restore();
}

function drawMinimapBeamFlash(ctx, size, state) {
  if (!beamFlash) return;
  const now = performance.now();
  const age = now - beamFlash.startTime;
  if (age >= BEAM_FLASH_MS) { beamFlash = null; return; }

  const PAD     = 6;
  const SECTOR  = 100_000;
  const mapW    = size - PAD * 2;
  const alpha   = (1 - age / BEAM_FLASH_MS) * 0.9;

  // Ship position on minimap.
  const sx = PAD + (state.position.x / SECTOR) * mapW;
  const sy = PAD + (state.position.y / SECTOR) * mapW;
  // Target position on minimap.
  const tx = PAD + (beamFlash.targetX / SECTOR) * mapW;
  const ty = PAD + (beamFlash.targetY / SECTOR) * mapW;

  ctx.save();
  ctx.strokeStyle = `rgba(0, 255, 65, ${alpha})`;
  ctx.lineWidth   = 1.5;
  ctx.beginPath();
  ctx.moveTo(sx, sy);
  ctx.lineTo(tx, ty);
  ctx.stroke();
  ctx.restore();
}

/**
 * Draw space station markers on the minimap (v0.05e).
 * Only transponder-active stations are shown.
 */
function drawMinimapStations(ctx, size) {
  if (!_stationEntities.length) return;

  const PAD    = 6;
  const SECTOR = 100_000;
  const mapW   = size - PAD * 2;

  ctx.save();
  for (const st of _stationEntities) {
    if (!st.transponder_active) continue;
    const sx = PAD + (st.x / SECTOR) * mapW;
    const sy = PAD + (st.y / SECTOR) * mapW;
    const color = st.faction === 'hostile' ? 'rgba(255, 64, 64, 0.8)'
                : st.faction === 'neutral'  ? 'rgba(255, 176, 0, 0.8)'
                :                             'rgba(0, 170, 255, 0.8)';
    // Small square marker for station.
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1;
    ctx.strokeRect(sx - 3, sy - 3, 6, 6);
  }
  ctx.restore();
}

/**
 * Draw hazard zones as tinted circles on the minimap.
 */
function drawMinimapHazards(ctx, size) {
  if (!hazards.length) return;

  const PAD      = 6;
  const mapW     = size - PAD * 2;
  const mapH     = size - PAD * 2;
  const SECTOR_W = 100_000;
  const SECTOR_H = 100_000;

  const HAZARD_COLOURS = {
    nebula:         'rgba(100, 60, 200, 0.18)',
    minefield:      'rgba(255, 80,  40, 0.22)',
    radiation_zone: 'rgba(180, 255, 60, 0.18)',
    gravity_well:   'rgba(60, 180, 255, 0.18)',
  };
  const HAZARD_BORDERS = {
    nebula:         'rgba(140, 80, 255, 0.45)',
    minefield:      'rgba(255, 80, 40,  0.55)',
    radiation_zone: 'rgba(180, 255, 60, 0.45)',
    gravity_well:   'rgba(60, 180, 255, 0.45)',
  };

  ctx.save();
  for (const hz of hazards) {
    const sx = PAD + (hz.x / SECTOR_W) * mapW;
    const sy = PAD + (hz.y / SECTOR_H) * mapH;
    const sr = (hz.radius / SECTOR_W) * mapW;

    ctx.beginPath();
    ctx.arc(sx, sy, sr, 0, Math.PI * 2);
    ctx.fillStyle   = HAZARD_COLOURS[hz.hazard_type] || 'rgba(255,255,255,0.1)';
    ctx.strokeStyle = HAZARD_BORDERS[hz.hazard_type] || 'rgba(255,255,255,0.3)';
    ctx.lineWidth   = 0.8;
    ctx.fill();
    ctx.stroke();
  }
  ctx.restore();
}

/**
 * Overlay enemy contacts on the minimap after drawMinimap() has already
 * drawn the base layer. Enemies are drawn as hostile-colour chevrons.
 */
function drawMinimapContacts(ctx, size, state) {
  if (!contacts.length) return;

  const PAD      = 6;
  const mapW     = size - PAD * 2;
  const mapH     = size - PAD * 2;
  const SECTOR_W = 100_000;
  const SECTOR_H = 100_000;
  const C_ENEMY  = '#ff4040';

  for (const contact of contacts) {
    const sx = PAD + Math.max(0, Math.min(1, contact.x / SECTOR_W)) * mapW;
    const sy = PAD + Math.max(0, Math.min(1, contact.y / SECTOR_H)) * mapH;
    const headRad = contact.heading * Math.PI / 180;
    drawShipChevron(ctx, sx, sy, headRad, 4, C_ENEMY);
  }
}

function updateTelemetry(state) {
  const hdg = Math.round(state.heading);
  const spd = state.velocity.toFixed(1);
  const thr = Math.round(state.throttle);
  const px  = Math.round(state.position.x);
  const py  = Math.round(state.position.y);

  telemHeading.textContent  = `${hdg.toString().padStart(3, '0')}°`;
  telemSpeed.textContent    = `${spd} u/s`;
  telemThrottle.textContent = `${thr}%`;
  telemPosX.textContent     = px.toLocaleString();
  telemPosY.textContent     = py.toLocaleString();
  speedBadge.textContent    = `${spd} u/s`;
}

// ---------------------------------------------------------------------------
// Zoom label
// ---------------------------------------------------------------------------

/** Handle range change from range control bar. */
function _onHelmRangeChange(key, worldUnits) {
  if (!_mapRenderer) return;
  if (key === 'SEC' && _sectorMap) {
    // Apply sector-centred view via SectorMap.
    _sectorMap.setZoomLevel('sector');
    _sectorMap._applyRangeToRenderer();
  } else if (key === 'STR') {
    // Strategic handled in drawNavMap via _rangeControl.isStrategic().
  } else {
    _mapRenderer.setRange(worldUnits);
    _mapRenderer.clearCameraOverride();
  }
}

// ---------------------------------------------------------------------------
// Keyboard controls
// ---------------------------------------------------------------------------

function _drawMinimapRoute(ctx, size, route) {
  const PAD = 6;
  const SECTOR = 100_000;
  const mapW = size - PAD * 2;
  const fromSx = PAD + (route.from_x / SECTOR) * mapW;
  const fromSy = PAD + (route.from_y / SECTOR) * mapW;
  const toSx   = PAD + (route.plot_x  / SECTOR) * mapW;
  const toSy   = PAD + (route.plot_y  / SECTOR) * mapW;
  const pulse  = 0.5 + 0.3 * Math.sin(performance.now() * 0.003);
  ctx.save();
  ctx.setLineDash([4, 3]);
  ctx.strokeStyle = `rgba(255, 176, 0, ${pulse})`;
  ctx.lineWidth   = 1;
  ctx.beginPath();
  ctx.moveTo(fromSx, fromSy);
  ctx.lineTo(toSx, toSy);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = `rgba(255, 176, 0, ${pulse})`;
  ctx.beginPath();
  ctx.arc(toSx, toSy, 3, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function setupKeyboard() {
  document.addEventListener('keydown', (e) => {
    const key = e.key.toLowerCase();
    // Range step via [ and ] is handled by RangeControl.
    // Z key — no longer used for zoom cycling.
    if (['arrowleft','arrowright','arrowup','arrowdown','a','d','w','s'].includes(key)) {
      e.preventDefault();
      if (!heldKeys.has(key)) {
        // Immediate first press — apply once right away.
        applyControl(key);
      }
      heldKeys.add(key);
    }
  });

  document.addEventListener('keyup', (e) => {
    heldKeys.delete(e.key.toLowerCase());
  });

  // Throttle slider input.
  throttleSlider.addEventListener('input', () => {
    if (!gameActive) return;
    throttle = parseInt(throttleSlider.value, 10);
    send('helm.set_throttle', { throttle });
    updateThrottleUI();
  });

  // Compass click — set target heading from click angle.
  compassCanvas.addEventListener('click', (e) => {
    if (!gameActive) return;
    const state = getInterpolatedState();
    if (!state) return;

    const rect = compassCanvas.getBoundingClientRect();
    const cx   = compassCanvas.width  / 2;
    const cy   = compassCanvas.height / 2;
    // Scale from CSS pixels to canvas pixels.
    const scaleX = compassCanvas.width  / rect.width;
    const scaleY = compassCanvas.height / rect.height;
    const dx = (e.clientX - rect.left) * scaleX - cx;
    const dy = (e.clientY - rect.top)  * scaleY - cy;

    // atan2(dy, dx) = angle from +x axis (canvas Y down = CW).
    // To get heading: clickAngle + currentHeading + 90°.
    // (Derivation: the ring is rotated so currentHeading is at top, which is
    // the -π/2 position in canvas space. See renderer.js drawCompass notes.)
    const clickDeg = Math.atan2(dy, dx) * 180 / Math.PI;
    targetHeading  = ((clickDeg + state.heading + 90) % 360 + 360) % 360;
    send('helm.set_heading', { heading: targetHeading });
    updateTargetHdgDisplay();
  });
}

/**
 * Held-key processing — called every rAF frame, but rate-limited to avoid
 * flooding the server.
 */
function processHeldKeys(now) {
  if (!gameActive) return;
  if (_dockedAt) return;  // controls locked while docked
  if (now - lastControlSend < TICK_MS) return;   // send at most 10/sec

  let headingChanged  = false;
  let throttleChanged = false;

  if (heldKeys.has('arrowleft') || heldKeys.has('a')) {
    targetHeading  = (targetHeading - HEADING_STEP + 360) % 360;
    headingChanged = true;
  } else if (heldKeys.has('arrowright') || heldKeys.has('d')) {
    targetHeading  = (targetHeading + HEADING_STEP) % 360;
    headingChanged = true;
  }

  if (heldKeys.has('arrowup') || heldKeys.has('w')) {
    throttle        = Math.min(100, throttle + THROTTLE_STEP);
    throttleChanged = true;
  } else if (heldKeys.has('arrowdown') || heldKeys.has('s')) {
    throttle        = Math.max(0, throttle - THROTTLE_STEP);
    throttleChanged = true;
  }

  if (headingChanged)  { send('helm.set_heading',  { heading: targetHeading }); updateTargetHdgDisplay(); }
  if (throttleChanged) { send('helm.set_throttle', { throttle }); updateThrottleUI(); }

  if (headingChanged || throttleChanged) lastControlSend = now;
}

/**
 * Immediate single application of a control key (on first press).
 */
function applyControl(key) {
  if (!gameActive) return;
  if (_dockedAt) return;  // controls locked while docked

  let headingChanged  = false;
  let throttleChanged = false;

  if (key === 'arrowleft'  || key === 'a') { targetHeading = (targetHeading - HEADING_STEP + 360) % 360; headingChanged  = true; }
  if (key === 'arrowright' || key === 'd') { targetHeading = (targetHeading + HEADING_STEP) % 360;       headingChanged  = true; }
  if (key === 'arrowup'    || key === 'w') { throttle = Math.min(100, throttle + THROTTLE_STEP);         throttleChanged = true; }
  if (key === 'arrowdown'  || key === 's') { throttle = Math.max(0, throttle - THROTTLE_STEP);           throttleChanged = true; }

  if (headingChanged)  { send('helm.set_heading',  { heading: targetHeading }); updateTargetHdgDisplay(); }
  if (throttleChanged) { send('helm.set_throttle', { throttle }); updateThrottleUI(); }
  lastControlSend = performance.now();
}

// ---------------------------------------------------------------------------
// UI update helpers
// ---------------------------------------------------------------------------

function updateTargetHdgDisplay() {
  targetHdgDisplay.textContent = `${Math.round(targetHeading).toString().padStart(3, '0')}°`;
}

function updateThrottleUI() {
  const pct = Math.round(throttle);
  throttleDisplay.textContent     = pct.toString().padStart(3, '0');
  throttleSlider.value            = pct;
  throttleGaugeFill.style.width   = `${pct}%`;
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
