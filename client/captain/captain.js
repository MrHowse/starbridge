/**
 * Captain Station — v0.04e
 *
 * Provides:
 *   - 4× wireframe viewports (Forward / Aft / Port / Starboard)
 *   - Ship silhouette + system controls (initShipStatus)
 *   - Alert level buttons
 *   - Tactical map canvas (North-up, MapRenderer)
 *   - Hull / shield quick-status
 *   - Science summary (scan progress + last result)
 *   - Mission objectives panel
 *   - Captain's log
 *   - Nuclear authorization panel
 *   - Victory / defeat overlay
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import { setStatusDot, setAlertLevel, showBriefing, showGameOver } from '../shared/ui_components.js';
import { SoundBank } from '../shared/audio.js';
import '../shared/audio_events.js';
import { wireButtonSounds } from '../shared/audio_ui.js';
import { registerHelp, initHelpOverlay } from '../shared/help_overlay.js';
import { initNotifications } from '../shared/notifications.js';
import { initRoleBar } from '../shared/role_bar.js';
import { MapRenderer } from '../shared/map_renderer.js';
import { SectorMap, ZOOM_RANGES } from '../shared/sector_map.js';
import {
  initViewports,
  updateViewportContacts,
  updateViewportShip,
  updateViewportAlert,
  triggerHullHitFlash,
  resizeViewports,
} from './wireframe.js';
import {
  initShipStatus,
  updateSystems,
  updateCrew,
  updateOverrides,
} from './ship_status.js';

registerHelp([
  { selector: '#captain-canvas',  text: 'Tactical map — North-up overview of all contacts.', position: 'right' },
  { selector: '.viewport-grid',   text: 'Wireframe viewports — perspective view of nearby contacts.', position: 'below' },
  { selector: '#silhouette-panel',text: 'Ship silhouette — click zones for detail. Toggle between Systems and Crew views.', position: 'left' },
  { selector: '.alert-btn',       text: 'Alert level — GREEN (normal), YELLOW (elevated), RED (battle stations).', position: 'below' },
]);

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAP_WORLD_RADIUS = 80_000;
const HIT_FLASH_MS     = 400;

// ---------------------------------------------------------------------------
// DOM refs — static
// ---------------------------------------------------------------------------

const statusDotEl    = document.querySelector('[data-status-dot]');
const statusLabelEl  = document.querySelector('[data-status-label]');
const standbyEl      = document.querySelector('[data-standby]');
const captainMainEl  = document.querySelector('[data-captain-main]');
const missionLabelEl = document.getElementById('mission-label');
const alertBtns      = document.querySelectorAll('.alert-btn');

// Tactical map
const mapCanvas = document.getElementById('captain-canvas');
const mapCtx    = mapCanvas ? mapCanvas.getContext('2d') : null;

// Quick-status bars
const hullFill      = document.getElementById('hull-fill');
const hullText      = document.getElementById('hull-text');
const shieldFwdFill = document.getElementById('shield-fwd-fill');
const shieldFwdText = document.getElementById('shield-fwd-text');
const shieldAftFill = document.getElementById('shield-aft-fill');
const shieldAftText = document.getElementById('shield-aft-text');

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

// Auth panel
const authPanel   = document.getElementById('auth-panel');
const authContent = document.getElementById('auth-content');

// Docking panel
const dockingPanel       = document.getElementById('docking-panel');
const dockingPanelTitle  = document.getElementById('docking-panel-title');
const dockingStationName = document.getElementById('docking-station-name');
const dockingServicesList = document.getElementById('docking-services-list');
const undockBtn          = document.getElementById('undock-btn');
const emergencyUndockBtn = document.getElementById('emergency-undock-btn');

// Log
const logList   = document.getElementById('log-list');
const logInput  = document.getElementById('log-input');
const logSubmit = document.getElementById('log-submit');

// Save
const saveBtn    = document.getElementById('save-game-btn');
const saveStatus = document.getElementById('save-status');

// Game over
const gameOverOverlay = document.getElementById('game-over-overlay');
const gameOverTitle   = document.getElementById('game-over-title');
const gameOverBody    = document.getElementById('game-over-body');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let gameActive   = false;
let currentAlert = 'green';
let shipState    = null;
let mapRenderer  = null;
let _sectorMap   = null;
let _pendingAuthId = null;
const _logEntries  = [];

// Science sector-scan status indicator (shown on tactical map).
let _scanIndicatorText = null;

// Zoom UI
const _mapZoomLabel = document.getElementById('map-zoom-label');
const _zoomBtns     = document.querySelectorAll('.zoom-btn');

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

function init() {
  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();
  });

  // Re-claim role on reconnect
  const playerName = sessionStorage.getItem('player_name');
  if (playerName) {
    on('lobby.welcome', () => {
      send('lobby.claim_role', { role: 'captain', player_name: playerName });
    });
  }

  // Alert buttons
  alertBtns.forEach(btn => {
    btn.addEventListener('click', () => send('captain.set_alert', { level: btn.dataset.alert }));
  });

  // Log panel wiring (HTML elements already exist)
  if (logSubmit) {
    logSubmit.addEventListener('click', _submitLog);
  }
  if (logInput) {
    logInput.addEventListener('keydown', e => { if (e.key === 'Enter') _submitLog(); });
  }

  // Save button
  if (saveBtn) {
    saveBtn.addEventListener('click', _saveGame);
  }

  on('game.saved', handleGameSaved);

  // Server messages
  on('game.started',                  handleGameStarted);
  on('ship.state',                    handleShipState);
  on('ship.alert_changed',            handleAlertChanged);
  on('world.entities',                handleWorldEntities);
  on('science.scan_progress',         handleScanProgress);
  on('science.scan_complete',         handleScanComplete);
  on('mission.objective_update',      handleObjectiveUpdate);
  on('ship.hull_hit',                 handleHullHit);
  on('captain.authorization_request', handleAuthorizationRequest);
  on('weapons.authorization_result',  handleAuthorizationResult);
  on('captain.log_entry',             handleLogEntry);
  on('captain.override_changed',      handleOverrideChanged);
  on('game.over',                     handleGameOver);
  on('map.sector_grid',               handleSectorGrid);
  on('map.scan_indicator',            handleScanIndicator);
  on('docking.complete',              handleDockingComplete);
  on('docking.undocked',              handleDockingUndocked);
  on('docking.service_complete',      handleDockingServiceComplete);

  // Docking controls
  if (undockBtn) {
    undockBtn.addEventListener('click', () => send('captain.undock', { emergency: false }));
  }
  if (emergencyUndockBtn) {
    emergencyUndockBtn.addEventListener('click', () => send('captain.undock', { emergency: true }));
  }

  // Zoom buttons
  _zoomBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      if (_sectorMap) _setZoom(btn.dataset.zoom);
    });
  });

  // Zoom keyboard shortcuts (Z cycle, 1/2/3 direct)
  document.addEventListener('keydown', (e) => {
    if (!gameActive || !_sectorMap) return;
    if (_sectorMap.handleKey(e.key)) {
      _updateZoomUI();
      e.preventDefault();
    }
  });

  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();
  initNotifications(send, 'captain');
  initRoleBar(send, 'captain');
  connect();
}

// ---------------------------------------------------------------------------
// Game started
// ---------------------------------------------------------------------------

function handleGameStarted(payload) {
  missionLabelEl.textContent  = (payload.mission_name || 'MISSION').toUpperCase();
  standbyEl.style.display     = 'none';
  captainMainEl.style.display = '';
  gameActive = true;

  // Wireframe viewports
  initViewports({
    forward:   document.getElementById('vp-forward'),
    aft:       document.getElementById('vp-aft'),
    port:      document.getElementById('vp-port'),
    starboard: document.getElementById('vp-starboard'),
  });

  // Ship silhouette + system controls
  const silhouetteCanvas = document.getElementById('ship-silhouette');
  const controlsList     = document.getElementById('system-controls-list');
  const viewToggleBtn    = document.getElementById('view-toggle-btn');
  if (silhouetteCanvas && controlsList && viewToggleBtn) {
    initShipStatus(
      silhouetteCanvas,
      controlsList,
      viewToggleBtn,
      (system, online) => send('captain.system_override', { system, online }),
    );
  }

  // Tactical map + sector map
  if (mapCanvas) {
    mapRenderer = new MapRenderer(mapCanvas, {
      range:          MAP_WORLD_RADIUS,
      orientation:    'north-up',
      showGrid:       true,
      showRangeRings: false,
      zoom:           { enabled: false },  // zoom handled by SectorMap
    });
    _sectorMap = new SectorMap({
      allowedLevels: ['tactical', 'sector', 'strategic'],
      defaultZoom:   'sector',
      onRoutePlot:   (wx, wy) => send('map.plot_route', { to_x: wx, to_y: wy }),
      onZoomChange:  _updateZoomUI,
    });
    _sectorMap.setMapRenderer(mapRenderer);
    _sectorMap.setupStrategicClick(mapCanvas);
    _buildDamageToggle();
    _updateZoomUI();
  }

  _resizeTactical();
  requestAnimationFrame(_tacticalLoop);

  if (saveBtn) saveBtn.style.display = '';

  if (payload.briefing_text) {
    showBriefing(payload.mission_name, payload.briefing_text);
  }
}

// ---------------------------------------------------------------------------
// Ship state
// ---------------------------------------------------------------------------

function handleShipState(payload) {
  shipState = payload;
  if (!gameActive) return;

  // Update viewports
  updateViewportShip(payload);

  // Update tactical map and sector map ship position
  if (mapRenderer) mapRenderer.updateShipState(payload);
  if (_sectorMap && payload.position) {
    _sectorMap.updateShipPosition(
      payload.position.x, payload.position.y, payload.heading ?? 0,
    );
  }

  // Update silhouette + system controls
  if (payload.systems)         updateSystems(payload.systems);
  if (payload.crew)            updateCrew(payload.crew);
  if (payload.system_overrides) updateOverrides(payload.system_overrides);

  // Quick-status hull / shields
  _updateQuickStatus(payload);

  // Docking panel visibility
  _updateDockingPanel(payload);
}

function _updateQuickStatus(state) {
  const hull    = Math.max(0, Math.min(100, state.hull || 0));
  const shields = state.shields || {};
  const fwd     = Math.max(0, Math.min(100, shields.front ?? 100));
  const aft     = Math.max(0, Math.min(100, shields.rear  ?? 100));

  if (hullFill)      hullFill.style.width      = `${hull}%`;
  if (hullText)      hullText.textContent       = Math.round(hull);
  if (shieldFwdFill) shieldFwdFill.style.width  = `${fwd}%`;
  if (shieldFwdText) shieldFwdText.textContent  = Math.round(fwd);
  if (shieldAftFill) shieldAftFill.style.width  = `${aft}%`;
  if (shieldAftText) shieldAftText.textContent  = Math.round(aft);
}

// ---------------------------------------------------------------------------
// Docking
// ---------------------------------------------------------------------------

let _dockedStationName = '';

function _updateDockingPanel(state) {
  if (!dockingPanel) return;
  const phase = state.docking_phase || 'none';
  const visible = phase === 'docked' || phase === 'sequencing' || phase === 'undocking';
  dockingPanel.style.display = visible ? '' : 'none';

  if (!visible) return;

  if (dockingPanelTitle) {
    dockingPanelTitle.textContent =
      phase === 'sequencing' ? 'DOCKING…' :
      phase === 'undocking'  ? 'UNDOCKING…' : 'DOCKED';
  }
  if (dockingStationName) {
    dockingStationName.textContent = _dockedStationName;
  }

  // Active services
  if (dockingServicesList) {
    const svcs = state.active_services || {};
    const entries = Object.entries(svcs);
    if (entries.length === 0) {
      dockingServicesList.textContent = 'No services running.';
    } else {
      dockingServicesList.innerHTML = entries
        .map(([svc, t]) => `<div>${svc.replace(/_/g, ' ').toUpperCase()} — ${Math.ceil(t)}s</div>`)
        .join('');
    }
  }
}

function handleDockingComplete({ station_name }) {
  _dockedStationName = station_name || '';
  if (dockingPanel) dockingPanel.style.display = '';
  if (dockingPanelTitle) dockingPanelTitle.textContent = 'DOCKED';
  if (dockingStationName) dockingStationName.textContent = _dockedStationName;
}

function handleDockingUndocked() {
  _dockedStationName = '';
  if (dockingPanel) dockingPanel.style.display = 'none';
}

function handleDockingServiceComplete({ service, effects }) {
  // Log notable effects.
  if (effects && effects.hull_restored > 0) {
    console.log(`Hull repair complete: +${effects.hull_restored} HP`);
  }
}

// ---------------------------------------------------------------------------
// Alert
// ---------------------------------------------------------------------------

function handleAlertChanged({ level }) {
  currentAlert = level;
  setAlertLevel(level);
  _updateAlertButtons(level);
  updateViewportAlert(level);
  SoundBank.setAmbient('alert_level', { level });
}

function _updateAlertButtons(level) {
  alertBtns.forEach(btn => {
    btn.classList.toggle('alert-btn--active', btn.dataset.alert === level);
  });
}

// ---------------------------------------------------------------------------
// World entities → viewports + tactical map
// ---------------------------------------------------------------------------

function handleWorldEntities(payload) {
  updateViewportContacts(payload.enemies || [], payload.torpedoes || []);
  if (mapRenderer) {
    mapRenderer.updateContacts(payload.enemies || [], payload.torpedoes || []);
    mapRenderer.updateHazards(payload.hazards || []);
  }
}

// ---------------------------------------------------------------------------
// Sector grid (map.sector_grid)
// ---------------------------------------------------------------------------

function handleSectorGrid(payload) {
  if (_sectorMap) _sectorMap.updateSectorGrid(payload);
}

// ---------------------------------------------------------------------------
// Science scan indicator (from map.scan_indicator)
// ---------------------------------------------------------------------------

function handleScanIndicator({ text }) {
  _scanIndicatorText = text || null;
}

// ---------------------------------------------------------------------------
// Zoom controls
// ---------------------------------------------------------------------------

function _setZoom(level) {
  if (!_sectorMap) return;
  _sectorMap.setZoomLevel(level);
  _updateZoomUI();
}

function _updateZoomUI() {
  if (!_sectorMap) return;
  const level = _sectorMap.getZoomLevel();
  if (_mapZoomLabel) _mapZoomLabel.textContent = _sectorMap.zoomLabel();
  _zoomBtns.forEach(btn => {
    btn.classList.toggle('zoom-btn--active', btn.dataset.zoom === level);
  });
}

// ---------------------------------------------------------------------------
// Hull hit
// ---------------------------------------------------------------------------

function handleHullHit() {
  if (!gameActive) return;
  SoundBank.play('hull_hit');
  triggerHullHitFlash();
  const el = document.getElementById('station-container') || document.querySelector('.station-container');
  if (el) {
    el.classList.add('hit');
    setTimeout(() => el.classList.remove('hit'), HIT_FLASH_MS);
  }
  if (mapRenderer && shipState?.position) {
    mapRenderer.addDamageEvent(shipState.position.x, shipState.position.y);
  }
}

// ---------------------------------------------------------------------------
// Science summary
// ---------------------------------------------------------------------------

function handleScanProgress({ entity_id, progress }) {
  if (scienceIdle)        scienceIdle.style.display    = 'none';
  if (scanActiveRow)      scanActiveRow.style.display  = '';
  if (scanEntityId)       scanEntityId.textContent      = entity_id;
  if (scanProgressFill)   scanProgressFill.style.width  = `${progress}%`;
}

function handleScanComplete({ entity_id, results }) {
  if (scanActiveRow)      scanActiveRow.style.display   = 'none';
  if (scanResultRow)      scanResultRow.style.display   = '';
  if (scanResultEntity)   scanResultEntity.textContent  = `${entity_id} (${results?.type || '?'})`;
  if (scanResultWeakness) scanResultWeakness.textContent = results?.weakness || 'No weakness detected.';
  if (scienceIdle)        scienceIdle.style.display      = 'none';
}

// ---------------------------------------------------------------------------
// Objectives
// ---------------------------------------------------------------------------

function handleObjectiveUpdate({ objectives }) {
  if (!objectivesList) return;
  if (!objectives || objectives.length === 0) {
    objectivesList.innerHTML = '<div class="text-dim">No objectives.</div>';
    return;
  }
  objectivesList.innerHTML = objectives.map(obj => {
    const complete = obj.status === 'complete';
    return `
      <div class="objective-row ${complete ? 'obj-complete' : 'obj-pending'}">
        <span class="obj-icon text-data">${complete ? '✓' : '○'}</span>
        <span class="obj-text text-body">${obj.text}</span>
      </div>`;
  }).join('');
}

// ---------------------------------------------------------------------------
// System overrides (from captain controls)
// ---------------------------------------------------------------------------

function handleOverrideChanged({ system, online }) {
  // updateOverrides is driven by ship.state; this is just for immediate UI
  // If ship.state hasn't arrived yet, still apply the known override state.
  if (shipState?.system_overrides) {
    shipState.system_overrides[system] = online;
    updateOverrides(shipState.system_overrides);
  }
}

// ---------------------------------------------------------------------------
// Authorization panel
// ---------------------------------------------------------------------------

function handleAuthorizationRequest({ request_id, tube }) {
  if (!gameActive || !authPanel || !authContent) return;
  _pendingAuthId = request_id;
  authContent.innerHTML = `
    <p class="text-body" style="font-size:.8rem">Tube ${tube} — Nuclear torpedo launch requested.</p>
    <div class="auth-btns">
      <button class="btn btn--danger" id="auth-approve-btn">AUTHORIZE LAUNCH</button>
      <button class="btn btn--secondary" id="auth-deny-btn">DENY</button>
    </div>
  `;
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
  authPanel.style.display = '';
}

function handleAuthorizationResult({ request_id }) {
  if (_pendingAuthId === request_id) _hideAuthPanel();
}

function _hideAuthPanel() {
  _pendingAuthId = null;
  if (authPanel) authPanel.style.display = 'none';
  if (authContent) authContent.innerHTML = '';
}

// ---------------------------------------------------------------------------
// Captain's log
// ---------------------------------------------------------------------------

function handleLogEntry({ text, timestamp }) {
  _logEntries.push({ text, timestamp });
  _renderLog();
}

function _submitLog() {
  const text = (logInput?.value || '').trim();
  if (!text || !gameActive) return;
  send('captain.add_log', { text });
  if (logInput) logInput.value = '';
}

function _renderLog() {
  if (!logList) return;
  if (_logEntries.length === 0) {
    logList.innerHTML = '<div class="text-dim" style="font-size:.7rem">No entries.</div>';
    return;
  }
  logList.innerHTML = _logEntries.map(e => {
    const d  = new Date(e.timestamp * 1000);
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    return `<div class="log-entry"><span class="log-ts">${hh}:${mm}</span><span>${e.text}</span></div>`;
  }).join('');
  logList.scrollTop = logList.scrollHeight;
}

// ---------------------------------------------------------------------------
// Save & resume
// ---------------------------------------------------------------------------

function _saveGame() {
  if (!gameActive || !saveBtn) return;
  saveBtn.disabled = true;
  if (saveStatus) saveStatus.textContent = 'Saving…';
  send('captain.save_game', {});
}

function handleGameSaved({ save_id }) {
  if (saveStatus) saveStatus.textContent = `Saved: ${save_id}`;
  // Brief pause so the captain can see the confirmation, then return to lobby.
  setTimeout(() => {
    window.location.href = '/client/lobby/';
  }, 1500);
}

// ---------------------------------------------------------------------------
// Game over
// ---------------------------------------------------------------------------

function handleGameOver({ result, stats = {} }) {
  gameActive = false;
  SoundBank.play(result === 'victory' ? 'victory' : 'defeat');
  SoundBank.stopAmbient('alert_level');

  if (gameOverTitle) gameOverTitle.textContent = result === 'victory' ? 'MISSION COMPLETE' : 'SHIP DESTROYED';

  const dur  = stats.duration_s != null
    ? `${Math.floor(stats.duration_s / 60)}:${String(Math.round(stats.duration_s % 60)).padStart(2, '0')}`
    : '—';
  const hull = stats.hull_remaining != null ? `${Math.round(stats.hull_remaining)}%` : '—';
  if (gameOverBody) {
    gameOverBody.textContent = result === 'victory'
      ? `All objectives achieved. Duration: ${dur}. Hull: ${hull}.`
      : `Hull integrity zero. Duration: ${dur}.`;
  }

  try {
    localStorage.setItem('starbridge_debrief', JSON.stringify({
      result,
      duration_s:     stats.duration_s     ?? null,
      hull_remaining: stats.hull_remaining  ?? null,
      captain_log:    stats.captain_log     ?? [],
      debrief:        stats.debrief         ?? null,
    }));
  } catch (_) { /* storage unavailable */ }

  const debriefBtn = document.getElementById('game-over-debrief-btn');
  if (debriefBtn && stats.debrief != null) debriefBtn.style.display = '';

  if (gameOverOverlay) gameOverOverlay.style.display = '';
}

// ---------------------------------------------------------------------------
// Tactical map helpers
// ---------------------------------------------------------------------------

function _resizeTactical() {
  if (!mapCanvas) return;
  const rect = mapCanvas.getBoundingClientRect();
  mapCanvas.width  = rect.width  || mapCanvas.offsetWidth;
  mapCanvas.height = rect.height || mapCanvas.offsetHeight;
}

function _tacticalLoop() {
  if (!gameActive) return;
  const now = performance.now();
  if (_sectorMap && _sectorMap.isStrategic()) {
    // Strategic view: render sector grid directly on map canvas.
    if (mapCanvas) _sectorMap.renderStrategic(mapCanvas, now);
  } else if (mapRenderer) {
    mapRenderer.render(now);
    // Station icons overlay (tactical / sector modes only).
    if (mapCtx && mapCanvas && _sectorMap) {
      _sectorMap.renderStationOverlay(mapCtx, mapCanvas, mapRenderer);
    }
    // Heading label overlay (tactical / sector modes only).
    if (mapCtx && shipState) {
      const W   = mapCanvas.width;
      const H   = mapCanvas.height;
      const hdg = Math.round(shipState.heading ?? 0).toString().padStart(3, '0');
      mapCtx.fillStyle    = 'rgba(0,255,65,0.3)';
      mapCtx.font         = '10px "Share Tech Mono",monospace';
      mapCtx.textAlign    = 'center';
      mapCtx.textBaseline = 'top';
      mapCtx.fillText(`HDG ${hdg}°`, W / 2, H / 2 + 14);
    }
  }
  // Science scan indicator overlay.
  if (mapCtx && _scanIndicatorText && mapCanvas) {
    const W = mapCanvas.width;
    const H = mapCanvas.height;
    mapCtx.save();
    mapCtx.font         = '9px "Share Tech Mono",monospace';
    mapCtx.textAlign    = 'left';
    mapCtx.textBaseline = 'bottom';
    mapCtx.fillStyle    = 'rgba(255,176,0,0.85)';
    mapCtx.fillText(_scanIndicatorText, 8, H - 6);
    mapCtx.restore();
  }
  requestAnimationFrame(_tacticalLoop);
}

function _buildDamageToggle() {
  const wrap = mapCanvas.parentElement;
  if (!wrap || wrap.querySelector('.map-overlay-btn')) return;

  const btn = document.createElement('button');
  btn.className   = 'map-overlay-btn';
  btn.textContent = 'DMG';
  btn.title       = 'Toggle damage impact overlay';
  btn.style.cssText = 'position:absolute;right:6px;top:6px;font:9px "Share Tech Mono",monospace;' +
    'background:transparent;border:1px solid rgba(0,255,65,0.3);color:rgba(0,255,65,0.5);' +
    'padding:2px 6px;cursor:pointer;letter-spacing:.08em;z-index:5;';

  let active = false;
  btn.addEventListener('click', () => {
    active = !active;
    mapRenderer.setDamageOverlay(active);
    btn.style.color       = active ? '#00ff41' : 'rgba(0,255,65,0.5)';
    btn.style.borderColor = active ? '#00ff41' : 'rgba(0,255,65,0.3)';
  });

  wrap.style.position = 'relative';
  wrap.appendChild(btn);
}

// ---------------------------------------------------------------------------
// Resize handlers
// ---------------------------------------------------------------------------

window.addEventListener('resize', () => {
  if (gameActive) {
    _resizeTactical();
    resizeViewports();
  }
});

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
