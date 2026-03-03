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
import { initCrewRoster } from '../shared/crew_roster.js';
import { MapRenderer } from '../shared/map_renderer.js';
import { SectorMap, ZOOM_RANGES } from '../shared/sector_map.js';
import { RangeControl, STATION_RANGES } from '../shared/range_control.js';
import {
  initViewports,
  updateViewportContacts,
  updateViewportShip,
  updateViewportAlert,
  triggerHullHitFlash,
  resizeViewports,
  setViewMode,
  setSingleCanvas,
  setHighlights,
  setLabels,
  setShipClass,
} from './wireframe.js';
import {
  initShipStatus,
  updateSystems,
  updateCrew,
  updateOverrides,
  updateRoster,
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

const MAP_WORLD_RADIUS = 100_000;
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
const hullFill       = document.getElementById('hull-fill');
const hullText       = document.getElementById('hull-text');
const shieldForeFill = document.getElementById('shield-fore-fill');
const shieldForeText = document.getElementById('shield-fore-text');
const shieldAftFill  = document.getElementById('shield-aft-fill');
const shieldAftText  = document.getElementById('shield-aft-text');
const shieldPortFill = document.getElementById('shield-port-fill');
const shieldPortText = document.getElementById('shield-port-text');
const shieldStarFill = document.getElementById('shield-star-fill');
const shieldStarText = document.getElementById('shield-star-text');

// Armour
const armourRow          = document.getElementById('armour-row');
const armourFill         = document.getElementById('armour-fill');
const armourText         = document.getElementById('armour-text');
const armourZonesEl      = document.getElementById('armour-zones-container');
const armourForeFill     = document.getElementById('armour-fore-fill');
const armourForeText     = document.getElementById('armour-fore-text');
const armourAftFill      = document.getElementById('armour-aft-fill');
const armourAftText      = document.getElementById('armour-aft-text');
const armourPortFill     = document.getElementById('armour-port-fill');
const armourPortText     = document.getElementById('armour-port-text');
const armourStarFill     = document.getElementById('armour-starboard-fill');
const armourStarText     = document.getElementById('armour-starboard-text');

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

// Missions panel
const missionsPanel       = document.getElementById('missions-panel');
const missionsCount       = document.getElementById('missions-count');
const missionOffer        = document.getElementById('mission-offer');
const offerTypeBadge      = document.getElementById('offer-type-badge');
const offerTitle          = document.getElementById('offer-title');
const offerBriefing       = document.getElementById('offer-briefing');
const offerObjectives     = document.getElementById('offer-objectives');
const offerRewards        = document.getElementById('offer-rewards');
const offerAssessment     = document.getElementById('offer-assessment');
const offerAssessmentText = document.getElementById('offer-assessment-text');
const offerDifficulty     = document.getElementById('offer-difficulty');
const offerDeadline       = document.getElementById('offer-deadline');
const offerConsequences   = document.getElementById('offer-consequences');
const offerDeclineText    = document.getElementById('offer-decline-text');
const acceptMissionBtn    = document.getElementById('accept-mission-btn');
const declineMissionBtn   = document.getElementById('decline-mission-btn');
const activeMissionsList  = document.getElementById('active-missions-list');

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
let _shipClass   = '';
const _logEntries  = [];

// Dynamic missions state
let _currentOffer = null;   // Currently displayed offer mission dict
let _activeMissions = [];   // Active/offered missions from server
let _missionWaypoints = []; // Waypoints to draw on tactical map

// Viewport mode controls
let _vpMode      = 'quad';
let _highlightsOn = false;
let _labelsOn     = false;

// Science sector-scan status indicator (shown on tactical map).
let _scanIndicatorText = null;

// Range control
let _rangeControl = null;

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

  // General order buttons (C.1.2)
  document.querySelectorAll('.order-btn[data-order]').forEach(btn => {
    btn.addEventListener('click', () => send('captain.set_general_order', { order: btn.dataset.order }));
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
  on('weapons.auto_fire_status',      handleAutoFireStatus);
  on('crew.roster',                   handleCrewRoster);
  on('comms.contacts',                handleCommsContacts);
  on('comms.contact_merged',          handleCommsContactMerged);
  on('mission.dynamic_list',          handleDynamicMissionList);
  on('mission.mission_offered',       handleMissionOffered);
  on('mission.mission_accepted',      handleMissionAccepted);
  on('mission.mission_declined',      handleMissionDeclined);
  on('mission.mission_completed',     handleMissionCompleted);
  on('mission.mission_failed',        handleMissionFailed);
  on('mission.mission_expired',       handleMissionExpired);
  on('mission.objective_completed',   handleMissionObjectiveCompleted);

  // Mission accept/decline buttons
  if (acceptMissionBtn) {
    acceptMissionBtn.addEventListener('click', () => {
      if (_currentOffer) send('captain.accept_mission', { mission_id: _currentOffer.id });
    });
  }
  if (declineMissionBtn) {
    declineMissionBtn.addEventListener('click', () => {
      if (_currentOffer) send('captain.decline_mission', { mission_id: _currentOffer.id });
    });
  }

  // Docking controls
  if (undockBtn) {
    undockBtn.addEventListener('click', () => send('captain.undock', { emergency: false }));
  }
  if (emergencyUndockBtn) {
    emergencyUndockBtn.addEventListener('click', () => send('captain.undock', { emergency: true }));
  }

  // Viewport keys (1–5 for mode, H/L for highlights/labels)
  document.addEventListener('keydown', (e) => {
    if (!gameActive) return;
    const VP_KEYS = { '1': 'fore', '2': 'aft', '3': 'port', '4': 'starboard', '5': 'quad' };
    if (VP_KEYS[e.key]) {
      _setVpMode(VP_KEYS[e.key]);
      e.preventDefault();
      return;
    }
    if (e.key === 'h' || e.key === 'H') {
      _highlightsOn = !_highlightsOn;
      setHighlights(_highlightsOn);
      _updateVpToolbarUI();
      e.preventDefault();
      return;
    }
    if (e.key === 'l' || e.key === 'L') {
      _labelsOn = !_labelsOn;
      setLabels(_labelsOn);
      _updateVpToolbarUI();
      e.preventDefault();
      return;
    }
  });

  _initViewportToolbar();

  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();
  initNotifications(send, 'captain');
  initRoleBar(send, 'captain');
  initCrewRoster(send);
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
  _shipClass = payload.ship_class || '';

  // Ship-class-specific panels
  const flagBridgePanel = document.getElementById('flag-bridge-panel');
  if (flagBridgePanel) flagBridgePanel.style.display = _shipClass === 'cruiser' ? '' : 'none';

  // Wireframe viewports
  initViewports({
    forward:   document.getElementById('vp-forward'),
    aft:       document.getElementById('vp-aft'),
    port:      document.getElementById('vp-port'),
    starboard: document.getElementById('vp-starboard'),
  });
  setSingleCanvas(document.getElementById('vp-single'));
  setShipClass(_shipClass);

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
      send,
    );
  }

  // Range control
  const rangeBarEl = document.getElementById('range-bar');
  if (rangeBarEl) {
    const cfg = STATION_RANGES.captain;
    _rangeControl = new RangeControl({
      container:    rangeBarEl,
      stationId:    'captain',
      ranges:       cfg.available,
      defaultRange: cfg.default,
      onChange:      _onCaptainRangeChange,
    });
    _rangeControl.attach();
  }

  // Tactical map + sector map
  if (mapCanvas) {
    mapRenderer = new MapRenderer(mapCanvas, {
      range:          _rangeControl ? _rangeControl.currentRangeUnits() : MAP_WORLD_RADIUS,
      orientation:    'north-up',
      showGrid:       true,
      showRangeRings: true,
      zoom:           { enabled: true },
      interactive:    true,
    });
    mapRenderer.onContactClick((contactId) => {
      send('captain.set_priority_target', { entity_id: contactId });
    });
    _sectorMap = new SectorMap({
      allowedLevels: ['tactical', 'sector', 'strategic'],
      defaultZoom:   'sector',
      onRoutePlot:   (wx, wy) => send('map.plot_route', { to_x: wx, to_y: wy }),
      onZoomChange:  () => {},
    });
    mapRenderer.loadShipSilhouette(_shipClass);
    _sectorMap.setMapRenderer(mapRenderer);
    _sectorMap.setupStrategicClick(mapCanvas);
    _buildDamageToggle();
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

  // C.1.2: General order display
  _updateOrderButtons(payload.general_order || null);
}

function handleCrewRoster(payload) {
  if (payload && payload.members) {
    updateRoster(Object.values(payload.members));
  }
}

function _updateQuickStatus(state) {
  const TOTAL = 200.0;
  const hull    = Math.max(0, Math.min(100, state.hull || 0));
  const shields = state.shields || {};
  const dist    = state.shield_distribution || { fore: 0.25, aft: 0.25, port: 0.25, starboard: 0.25 };

  if (hullFill) hullFill.style.width = `${hull}%`;
  if (hullText) hullText.textContent = Math.round(hull);

  // Armour bar (ships with armour_max > 0)
  const armMax = state.armour_max || 0;
  if (armourRow) armourRow.style.display = armMax > 0 ? '' : 'none';
  if (armMax > 0) {
    const arm = Math.max(0, state.armour || 0);
    const armPct = Math.min(100, (arm / armMax) * 100);
    if (armourFill) armourFill.style.width = `${armPct}%`;
    if (armourText) armourText.textContent = Math.round(arm);
  }

  // Armour zones (battleship only)
  const zones = state.armour_zones;
  const zonesMax = state.armour_zones_max;
  if (armourZonesEl) armourZonesEl.style.display = zones && zonesMax ? '' : 'none';
  if (zones && zonesMax) {
    const zoneMap = [
      { fill: armourForeFill, text: armourForeText, key: 'fore' },
      { fill: armourAftFill,  text: armourAftText,  key: 'aft' },
      { fill: armourPortFill, text: armourPortText,  key: 'port' },
      { fill: armourStarFill, text: armourStarText,  key: 'starboard' },
    ];
    for (const { fill, text, key } of zoneMap) {
      const zhp = Math.max(0, zones[key] ?? 0);
      const zmax = zonesMax[key] ?? 1;
      const zpct = zmax > 0 ? Math.min(100, (zhp / zmax) * 100) : 0;
      if (fill) fill.style.width = `${zpct}%`;
      if (text) text.textContent = Math.round(zhp);
    }
  }

  const facingMap = [
    { fill: shieldForeFill, text: shieldForeText, key: 'fore' },
    { fill: shieldAftFill,  text: shieldAftText,  key: 'aft'  },
    { fill: shieldPortFill, text: shieldPortText,  key: 'port' },
    { fill: shieldStarFill, text: shieldStarText,  key: 'starboard' },
  ];
  for (const { fill, text, key } of facingMap) {
    const hp    = Math.max(0, shields[key] ?? 50);
    const maxHp = TOTAL * (dist[key] ?? 0.25);
    const pct   = maxHp > 0 ? Math.min(100, (hp / maxHp) * 100) : 0;
    if (fill) fill.style.width  = `${pct}%`;
    if (text) text.textContent  = Math.round(hp);
  }
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
// Auto-fire status
// ---------------------------------------------------------------------------

let _autoFireActive = false;

function handleAutoFireStatus({ active }) {
  _autoFireActive = active;
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

function _updateOrderButtons(order) {
  document.querySelectorAll('.order-btn[data-order]').forEach(btn => {
    btn.classList.toggle('order-btn--active', btn.dataset.order === order);
  });
  const lbl = document.getElementById('active-order-label');
  if (lbl) lbl.textContent = order ? order.replace(/_/g, ' ').toUpperCase() : '';
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
// Comms intelligence contacts
// ---------------------------------------------------------------------------

function handleCommsContacts(payload) {
  if (mapRenderer) {
    mapRenderer.updateCommsContacts(payload.contacts || []);
  }
}

function handleCommsContactMerged(payload) {
  // Visual feedback could be added here (flash effect, notification)
}

// ---------------------------------------------------------------------------
// Dynamic missions
// ---------------------------------------------------------------------------

const DIFFICULTY_BARS = {
  easy: '██░░░', moderate: '███░░', hard: '████░', dangerous: '█████', unknown: '??░░░',
};

const TYPE_LABELS = {
  rescue: 'RESCUE', escort: 'ESCORT', investigate: 'INVESTIGATE', intercept: 'INTERCEPT',
  patrol: 'PATROL', salvage: 'SALVAGE', trade: 'TRADE', diplomatic: 'DIPLOMATIC',
};

function handleDynamicMissionList({ missions }) {
  if (!missions || !missionsPanel) return;
  _activeMissions = missions;

  const offered = missions.filter(m => m.status === 'offered');
  const active  = missions.filter(m => m.status === 'active' || m.status === 'accepted');

  // Show/hide panel
  missionsPanel.style.display = missions.length > 0 ? '' : 'none';
  if (missionsCount) {
    missionsCount.textContent = active.length > 0 ? `${active.length} ACTIVE` : '';
  }

  // Show first offered mission if no current offer displayed
  if (offered.length > 0 && (!_currentOffer || !offered.find(m => m.id === _currentOffer.id))) {
    _showMissionOffer(offered[0]);
  } else if (offered.length === 0) {
    _hideMissionOffer();
  }

  // Update deadlines on current offer
  if (_currentOffer) {
    const offerData = offered.find(m => m.id === _currentOffer.id);
    if (offerData && offerDeadline) {
      _updateOfferDeadline(offerData);
    }
  }

  // Render active missions tracker
  _renderActiveMissions(active);

  // Update waypoints for map
  _missionWaypoints = active
    .filter(m => m.waypoint)
    .map(m => ({ x: m.waypoint[0], y: m.waypoint[1], name: m.waypoint_name || m.title }));
}

function _showMissionOffer(m) {
  _currentOffer = m;
  if (!missionOffer) return;
  missionOffer.style.display = '';

  // Type badge
  if (offerTypeBadge) {
    offerTypeBadge.textContent = TYPE_LABELS[m.mission_type] || m.mission_type.toUpperCase();
    offerTypeBadge.className = `mission-offer__type mission-offer__type--${m.mission_type}`;
  }

  // Title & briefing
  if (offerTitle) offerTitle.textContent = m.title;
  if (offerBriefing) offerBriefing.textContent = m.briefing;

  // Objectives
  if (offerObjectives) {
    offerObjectives.innerHTML = (m.objectives || []).map((o, i) => {
      const opt = o.optional ? ' <span class="text-dim">(optional)</span>' : '';
      return `<div>${i + 1}. ${o.description}${opt}</div>`;
    }).join('');
  }

  // Rewards
  if (offerRewards && m.rewards) {
    offerRewards.textContent = m.rewards.description || 'Unknown rewards';
  }

  // Comms assessment
  if (offerAssessment && offerAssessmentText) {
    if (m.comms_assessment) {
      offerAssessment.style.display = '';
      offerAssessmentText.textContent = `"${m.comms_assessment}"`;
    } else {
      offerAssessment.style.display = 'none';
    }
  }

  // Difficulty
  if (offerDifficulty) {
    const bars = DIFFICULTY_BARS[m.estimated_difficulty] || '??░░░';
    offerDifficulty.textContent = `${bars} ${(m.estimated_difficulty || 'unknown').toUpperCase()}`;
  }

  // Deadline
  _updateOfferDeadline(m);

  // Decline consequences
  if (offerConsequences && offerDeclineText) {
    const dc = m.decline_consequences;
    if (dc && dc.description) {
      offerConsequences.style.display = '';
      offerDeclineText.textContent = dc.description;
    } else {
      offerConsequences.style.display = 'none';
    }
  }
}

function _updateOfferDeadline(m) {
  if (!offerDeadline) return;
  if (m.accept_deadline != null && m.accept_deadline > 0) {
    const secs = Math.ceil(m.accept_deadline);
    const mm = Math.floor(secs / 60);
    const ss = (secs % 60).toString().padStart(2, '0');
    offerDeadline.textContent = `DEADLINE: ${mm}:${ss}`;
    offerDeadline.className = secs <= 15
      ? 'mission-offer__deadline mission-offer__deadline--urgent'
      : 'mission-offer__deadline';
  } else {
    offerDeadline.textContent = '';
  }
}

function _hideMissionOffer() {
  _currentOffer = null;
  if (missionOffer) missionOffer.style.display = 'none';
}

function _renderActiveMissions(active) {
  if (!activeMissionsList) return;
  if (active.length === 0) {
    activeMissionsList.innerHTML = '';
    return;
  }
  activeMissionsList.innerHTML = active.map(m => {
    const objs = (m.objectives || []).map(o => {
      const done = o.completed;
      return `<div class="active-mission__obj ${done ? 'active-mission__obj--done' : 'active-mission__obj--pending'}">
        <span class="obj-check">${done ? '✓' : '○'}</span>
        <span>${o.description}${o.optional ? ' (opt)' : ''}</span>
      </div>`;
    }).join('');

    let timer = '';
    if (m.completion_deadline != null && m.completion_deadline > 0) {
      const secs = Math.ceil(m.completion_deadline);
      const mm = Math.floor(secs / 60);
      const ss = (secs % 60).toString().padStart(2, '0');
      const cls = secs <= 30 ? 'active-mission__timer active-mission__timer--urgent' : 'active-mission__timer';
      timer = `<span class="${cls}">${mm}:${ss}</span>`;
    }

    return `<div class="active-mission">
      <div class="active-mission__header">
        <span class="active-mission__title">${m.title}</span>
        ${timer}
      </div>
      ${objs}
    </div>`;
  }).join('');
}

function handleMissionOffered({ mission }) {
  if (!mission) return;
  _showMissionOffer(mission);
  if (missionsPanel) missionsPanel.style.display = '';
}

function handleMissionAccepted({ mission }) {
  _hideMissionOffer();
}

function handleMissionDeclined({ mission_id }) {
  if (_currentOffer && _currentOffer.id === mission_id) _hideMissionOffer();
}

function handleMissionCompleted({ mission_id, title, rewards }) {
  if (_currentOffer && _currentOffer.id === mission_id) _hideMissionOffer();
  // Could add notification toast here
}

function handleMissionFailed({ mission_id, title, reason }) {
  if (_currentOffer && _currentOffer.id === mission_id) _hideMissionOffer();
}

function handleMissionExpired({ mission_id }) {
  if (_currentOffer && _currentOffer.id === mission_id) _hideMissionOffer();
}

function handleMissionObjectiveCompleted({ mission_id, objective_id, description }) {
  // Active missions list will re-render on next dynamic_list tick
}

// ---------------------------------------------------------------------------
// Sector grid (map.sector_grid)
// ---------------------------------------------------------------------------

function handleSectorGrid(payload) {
  if (_sectorMap) _sectorMap.updateSectorGrid(payload);

  // Feed sector bounds to range control for SEC auto-calc.
  if (_rangeControl && payload) {
    const active = (payload.sectors || []).find(s => s.visibility === 'active');
    if (active) {
      const SECTOR_SIZE = 100_000;
      const cx = active.col * SECTOR_SIZE + SECTOR_SIZE / 2;
      const cy = active.row * SECTOR_SIZE + SECTOR_SIZE / 2;
      _rangeControl.setSectorBounds(cx, cy, SECTOR_SIZE);
    }
    _rangeControl.setStrategicGrid(payload);
  }
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

function _onCaptainRangeChange(key, worldUnits) {
  if (key === 'SEC' && _sectorMap && _rangeControl) {
    const { x, y } = _rangeControl.getSectorCentre();
    _sectorMap.setZoomLevel('sector');
    if (mapRenderer) {
      mapRenderer.setRange(worldUnits);
      mapRenderer.setCameraOverride(x, y);
    }
    return;
  }
  if (key === 'STR' && _sectorMap) {
    _sectorMap.setZoomLevel('strategic');
    return;
  }
  // Normal range: tactical mode on SectorMap, direct range on renderer.
  if (_sectorMap) _sectorMap.setZoomLevel('tactical');
  if (mapRenderer) {
    mapRenderer.setRange(worldUnits);
    mapRenderer.clearCameraOverride();
  }
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
// Viewport mode + toolbar
// ---------------------------------------------------------------------------

function _initViewportToolbar() {
  document.querySelectorAll('.vp-mode-btn').forEach(btn => {
    btn.addEventListener('click', () => _setVpMode(btn.dataset.mode));
  });
  document.getElementById('highlights-btn')?.addEventListener('click', () => {
    _highlightsOn = !_highlightsOn;
    setHighlights(_highlightsOn);
    _updateVpToolbarUI();
  });
  document.getElementById('labels-btn')?.addEventListener('click', () => {
    _labelsOn = !_labelsOn;
    setLabels(_labelsOn);
    _updateVpToolbarUI();
  });
}

function _setVpMode(mode) {
  _vpMode = mode;
  setViewMode(mode);
  const grid   = document.getElementById('viewport-grid');
  const single = document.getElementById('viewport-single');
  if (grid)   grid.style.display   = mode === 'quad' ? '' : 'none';
  if (single) single.style.display = mode === 'quad' ? 'none' : 'block';
  resizeViewports();
  _updateVpToolbarUI();
}

function _updateVpToolbarUI() {
  document.querySelectorAll('.vp-mode-btn').forEach(btn => {
    btn.classList.toggle('vp-mode-btn--active', btn.dataset.mode === _vpMode);
  });
  const hBtn = document.getElementById('highlights-btn');
  const lBtn = document.getElementById('labels-btn');
  if (hBtn) {
    hBtn.dataset.on  = _highlightsOn;
    hBtn.textContent = `HIGHLIGHTS: ${_highlightsOn ? 'ON' : 'OFF'}`;
    hBtn.classList.toggle('vp-toggle-btn--on', _highlightsOn);
  }
  if (lBtn) {
    lBtn.dataset.on  = _labelsOn;
    lBtn.textContent = `LABELS: ${_labelsOn ? 'ON' : 'OFF'}`;
    lBtn.classList.toggle('vp-toggle-btn--on', _labelsOn);
  }
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
  if (_rangeControl && _rangeControl.isStrategic() && _sectorMap) {
    // Strategic view: render sector grid directly on map canvas.
    _sectorMap.setZoomLevel('strategic');
    if (mapCanvas) _sectorMap.renderStrategic(mapCanvas, now);
  } else if (mapRenderer) {
    mapRenderer.render(now);
    // Station icons overlay (tactical / sector modes only).
    if (mapCtx && mapCanvas && _sectorMap) {
      _sectorMap.renderStationOverlay(mapCtx, mapCanvas, mapRenderer);
    }
    // Sector boundary + adjacent sector labels.
    if (mapCtx && mapCanvas && _sectorMap && _rangeControl && _rangeControl.isSector()) {
      _sectorMap.renderSectorBoundaryOverlay(mapCtx, mapCanvas, mapRenderer);
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
    // Mission waypoint markers.
    if (mapCtx && mapRenderer && _missionWaypoints.length > 0) {
      const pulse = 0.5 + 0.5 * Math.sin(now / 600);
      mapCtx.save();
      for (const wp of _missionWaypoints) {
        const sp = mapRenderer.worldToCanvas(wp.x, wp.y);
        if (sp.x < -20 || sp.x > mapCanvas.width + 20 ||
            sp.y < -20 || sp.y > mapCanvas.height + 20) continue;
        const s = 6;
        const alpha = 0.5 + 0.4 * pulse;
        mapCtx.strokeStyle = `rgba(255,176,0,${alpha})`;
        mapCtx.lineWidth = 1.5;
        mapCtx.beginPath();
        mapCtx.moveTo(sp.x, sp.y - s); mapCtx.lineTo(sp.x + s, sp.y);
        mapCtx.lineTo(sp.x, sp.y + s); mapCtx.lineTo(sp.x - s, sp.y);
        mapCtx.closePath();
        mapCtx.stroke();
        // Label
        mapCtx.font         = '8px "Share Tech Mono",monospace';
        mapCtx.textAlign    = 'center';
        mapCtx.textBaseline = 'bottom';
        mapCtx.fillStyle    = `rgba(255,176,0,${alpha})`;
        mapCtx.fillText(wp.name || 'WAYPOINT', sp.x, sp.y - s - 3);
      }
      mapCtx.restore();
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
  // Weapons crewing status overlay.
  if (mapCtx && mapCanvas) {
    const auto = shipState?.auto_fire_active ?? false;
    mapCtx.save();
    mapCtx.font         = '9px "Share Tech Mono",monospace';
    mapCtx.textAlign    = 'right';
    mapCtx.textBaseline = 'bottom';
    mapCtx.fillStyle    = auto
      ? 'rgba(255,176,0,0.85)'   // amber
      : 'rgba(0,255,65,0.6)';    // green
    mapCtx.fillText(
      auto ? 'WEAPONS: AUTO (50%)' : 'WEAPONS: CREWED',
      mapCanvas.width - 8, mapCanvas.height - 6,
    );
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
