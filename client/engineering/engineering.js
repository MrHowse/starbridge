/**
 * Starbridge — Engineering Station (v0.06.2)
 *
 * Three-column command centre with power management, ship interior map,
 * repair team dispatch, and component-level diagnostics.
 *
 * Server messages received:
 *   ship.state              — full system snapshot (power, health, efficiency)
 *   engineering.state        — components, repair teams, power grid, battery, orders
 *   engineering.dc_state     — room hazard states for interior map
 *   ship.system_damaged      — immediate health update flash
 *   ship.hull_hit            — red flash on station border
 *   captain.override_changed — system taken offline by Captain
 *   game.started             — mission begins
 *   game.over                — mission ends
 *
 * Server messages sent:
 *   engineering.set_power       { system, level }
 *   engineering.set_repair      { system }
 *   engineering.dispatch_team   { team_id, system }
 *   engineering.recall_team     { team_id }
 *   engineering.set_battery_mode { mode }
 *   engineering.start_reroute   { target_bus }
 *   engineering.request_escort  { team_id }
 *   engineering.cancel_repair_order { order_id }
 *   engineering.dispatch_dct    { room_id }
 *   engineering.cancel_dct      { room_id }
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import { setStatusDot, setAlertLevel, showBriefing, showGameOver } from '../shared/ui_components.js';
import { drawBackground } from '../shared/renderer.js';
import { initPuzzleRenderer } from '../shared/puzzle_renderer.js';
import { SoundBank } from '../shared/audio.js';
import '../shared/audio_ambient.js';
import '../shared/audio_events.js';
import { wireButtonSounds } from '../shared/audio_ui.js';
import { registerHelp, initHelpOverlay } from '../shared/help_overlay.js';
import { initNotifications } from '../shared/notifications.js';
import { initRoleBar } from '../shared/role_bar.js';

registerHelp([
  { selector: '#systems-container', text: 'Power sliders — drag to allocate power (0–150%). Keys 1-9 select system.', position: 'right' },
  { selector: '#interior-map',      text: 'Ship interior — shows damage, repair teams, and hazards.', position: 'left' },
  { selector: '#components-container', text: 'Component detail — shows sub-component health for selected system.', position: 'left' },
  { selector: '#budget-readout',    text: 'Power budget — total demand vs reactor output.', position: 'below' },
]);

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POWER_BUDGET        = 900;    // 9 systems × 100
const OVERCLOCK_THRESHOLD = 100;
const DAMAGE_FLASH_MS     = 500;

const C_HEALTHY  = '#00ff41';
const C_WARNING  = '#ffb000';
const C_CRITICAL = '#ff2020';
const C_OFFLINE  = '#444444';

// Interior map canvas constants (matching Security station geometry)
const ROOM_W   = 160;
const ROOM_H   = 96;
const ROOM_GAP = 24;
const ROOM_MARGIN = 48;

// ---------------------------------------------------------------------------
// System definitions — all 9 systems
// ---------------------------------------------------------------------------

const SYSTEM_DEFS = [
  { key: 'sensors',       label: 'SENSORS',     shortKey: '1' },
  { key: 'shields',       label: 'SHIELDS',     shortKey: '2' },
  { key: 'beams',         label: 'BEAMS',       shortKey: '3' },
  { key: 'torpedoes',     label: 'TORPEDOES',   shortKey: '4' },
  { key: 'manoeuvring',   label: 'MANOEUV.',    shortKey: '5' },
  { key: 'engines',       label: 'ENGINES',     shortKey: '6' },
  { key: 'flight_deck',   label: 'FLT DECK',    shortKey: '7' },
  { key: 'ecm_suite',     label: 'ECM',         shortKey: '8' },
  { key: 'point_defence', label: 'PT DEFENCE',  shortKey: '9' },
];

const BATTERY_MODES = ['charging', 'standby', 'discharging', 'auto'];

const OVERLAY_MODES = ['damage', 'teams', 'hazards', 'all'];

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusDotEl        = document.querySelector('[data-status-dot]');
const statusLabelEl      = document.querySelector('[data-status-label]');
const standbyEl          = document.querySelector('[data-standby]');
const engMainEl          = document.querySelector('[data-eng-main]');
const statusBarEl        = document.querySelector('[data-statusbar]');
const missionLabelEl     = document.getElementById('mission-label');
const reactorReadoutEl   = document.getElementById('reactor-readout');
const reactorGaugeFill   = document.getElementById('reactor-gauge-fill');
const batteryReadoutEl   = document.getElementById('battery-readout');
const batteryGaugeFill   = document.getElementById('battery-gauge-fill');
const batteryModesEl     = document.getElementById('battery-modes');
const budgetReadoutEl    = document.getElementById('budget-readout');
const budgetGaugeFill    = document.getElementById('budget-gauge-fill');
const systemsContainer   = document.getElementById('systems-container');
const repairQueueCountEl = document.getElementById('repair-queue-count');
const repairQueueListEl  = document.getElementById('repair-queue-list');
const interiorCanvas     = document.getElementById('interior-map');
const overlaySelectorEl  = document.getElementById('overlay-selector');
const teamCardsEl        = document.getElementById('team-cards');
const detailTitleEl      = document.getElementById('detail-title');
const componentsEl       = document.getElementById('components-container');
const dispatchControlsEl = document.getElementById('dispatch-controls');
const dispatchTeamListEl = document.getElementById('dispatch-team-list');
const damageLogListEl    = document.getElementById('damage-log-list');

// Status bar
const sbPowerVal     = document.getElementById('sb-power-val');
const sbBatteryVal   = document.getElementById('sb-battery-val');
const sbTeamsVal     = document.getElementById('sb-teams-val');
const sbBusVal       = document.getElementById('sb-bus-val');
const sbEmergencyVal = document.getElementById('sb-emergency-val');
const sbEmergencyEl  = document.getElementById('sb-emergency');

// ---------------------------------------------------------------------------
// Game state
// ---------------------------------------------------------------------------

let gameActive     = false;
let hintsEnabled   = false;
let currShipState  = null;    // most recent ship.state payload
let currEngState   = null;    // most recent engineering.state payload
let selectedSystem = null;    // key of the system selected in detail panel
let repairFocus    = null;    // key of the system currently being repaired
let activeOverlay  = 'damage';

// Interior map
let interiorLayout = {};      // room_id → {name, deck, col, row, connections}
let roomStates     = {};      // room_id → {state, door_sealed}
let activeDcts     = {};      // room_id → progress 0..1
let ictx           = null;    // interior canvas context
let canvasW        = 808;
let canvasH        = 672;

const flashSystems = {};      // system_key → timestamp of last damage flash

/** Per-system DOM element cache. */
const sysEls = {};

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();
  });

  on('lobby.welcome', (payload) => {
    const name = sessionStorage.getItem('player_name') || 'ENGINEERING';
    send('lobby.claim_role', { role: 'engineering', player_name: name });
    console.log('[engineering] Connected as', payload.connection_id);
  });

  on('game.started',             handleGameStarted);
  on('ship.state',               handleShipState);
  on('engineering.state',        handleEngState);
  on('engineering.dc_state',     handleDCState);
  on('ship.system_damaged',      handleSystemDamaged);
  on('ship.hull_hit',            handleHullHit);
  on('ship.alert_changed',       ({ level }) => setAlertLevel(level));
  on('game.over',                handleGameOver);
  on('puzzle.assist_available',  handleAssistAvailable);
  on('puzzle.assist_sent',       handleAssistSent);
  on('captain.override_changed', handleCaptainOverride);

  setupBatteryModeButtons();
  setupOverlayButtons();
  setupKeyboard();

  initPuzzleRenderer(send);
  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();
  initNotifications(send, 'engineering');
  initRoleBar(send, 'engineering');
  connect();
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function handleGameStarted(payload) {
  missionLabelEl.textContent = payload.mission_name.toUpperCase();
  standbyEl.style.display    = 'none';
  engMainEl.style.display    = 'grid';
  statusBarEl.style.display  = 'flex';

  // Store interior layout for the map
  interiorLayout = payload.interior_layout || {};

  // Compute canvas size from layout
  computeCanvasSize();

  // Build system rows
  buildSystemRows();
  gameActive = true;

  // Setup interior canvas
  requestAnimationFrame(() => {
    ictx = interiorCanvas.getContext('2d');
    interiorCanvas.width  = canvasW;
    interiorCanvas.height = canvasH;
    requestAnimationFrame(renderLoop);
  });

  if (payload.briefing_text) {
    showBriefing(payload.mission_name, payload.briefing_text);
  }

  hintsEnabled = payload.difficulty === 'cadet';
  console.log(`[engineering] Game started — mission: ${payload.mission_id}`);
  SoundBank.setAmbient('reactor_drone', { powerLoad: 0.5 });
}

function handleGameOver(payload) {
  gameActive = false;
  SoundBank.play(payload.result === 'victory' ? 'victory' : 'defeat');
  SoundBank.stopAmbient('reactor_drone');
  SoundBank.stopAmbient('alert_level');
  showGameOver(payload.result, payload.stats || {});
}

function handleShipState(payload) {
  if (!gameActive) return;
  currShipState = payload;
  applyShipState(payload);
  const totalPwr = Object.values(payload.systems || {}).reduce((s, sys) => s + (sys.power || 0), 0);
  SoundBank.setAmbient('reactor_drone', { powerLoad: totalPwr / POWER_BUDGET });
}

function handleEngState(payload) {
  if (!gameActive) return;
  currEngState = payload;
  applyEngState(payload);
}

function handleDCState(payload) {
  if (!gameActive) return;
  roomStates  = payload.rooms || {};
  activeDcts  = payload.active_dcts || {};
}

function handleSystemDamaged(payload) {
  SoundBank.play('system_damage');
  flashSystems[payload.system] = performance.now();

  if (currShipState?.systems?.[payload.system] != null) {
    currShipState.systems[payload.system].health = payload.new_health;
  }
  const els = sysEls[payload.system];
  if (els) {
    updateHealthDOM(payload.system, payload.new_health, els);
  }
}

function handleHullHit() {
  SoundBank.play('hull_hit');
  const el = document.querySelector('.station-container') || document.body;
  el.style.transition = 'outline 0.05s ease';
  el.style.outline    = '3px solid #ff2020';
  setTimeout(() => { el.style.outline = ''; }, 500);
}

function handleCaptainOverride({ system, online }) {
  const els = sysEls[system];
  if (!els) return;

  els.row.classList.toggle('sys-row--override', !online);

  let badge = els.row.querySelector('.sys-row__override-badge');
  if (!online) {
    if (!badge) {
      badge = document.createElement('span');
      badge.className   = 'sys-row__override-badge';
      badge.textContent = 'OFFLINE';
      els.row.appendChild(badge);
    }
    if (els.slider) els.slider.disabled = true;
  } else {
    if (badge) badge.remove();
    if (els.slider) els.slider.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Cross-station assist notification
// ---------------------------------------------------------------------------

let _assistPanel = null;

function handleAssistAvailable(payload) {
  if (_assistPanel) _assistPanel.remove();

  const panel = document.createElement('div');
  panel.className = 'assist-panel panel';
  panel.innerHTML = `
    <div class="panel__header">
      <span class="text-label">SENSOR ASSIST AVAILABLE</span>
    </div>
    <p class="assist-panel__msg text-data">${escapeHtml(payload.instructions)}</p>
  `;
  const container = document.querySelector('.station-container');
  if (container) container.appendChild(panel);
  _assistPanel = panel;
}

function handleAssistSent(payload) {
  if (!_assistPanel) return;
  const msgEl = _assistPanel.querySelector('.assist-panel__msg');
  if (msgEl) {
    msgEl.textContent = payload.message || 'Calibration data relayed to Science.';
    msgEl.classList.add('assist-panel__msg--sent');
  }
  setTimeout(() => {
    if (_assistPanel) { _assistPanel.remove(); _assistPanel = null; }
  }, 4000);
}

// ---------------------------------------------------------------------------
// Ship state → DOM (left panel system sliders)
// ---------------------------------------------------------------------------

function applyShipState(state) {
  if (state.alert_level) setAlertLevel(state.alert_level);

  if (state.repair_focus !== repairFocus) {
    repairFocus = state.repair_focus ?? null;
    updateRepairFocusDOM();
  }

  let totalPower = 0;

  for (const def of SYSTEM_DEFS) {
    const sys = state.systems?.[def.key];
    const els = sysEls[def.key];
    if (!sys || !els) continue;

    totalPower += sys.power;

    updateHealthDOM(def.key, sys.health, els);

    const serverPwr = Math.round(sys.power);
    if (parseInt(els.slider.value, 10) !== serverPwr) {
      els.slider.value = serverPwr;
    }
    updateSliderBackground(els.slider, sys.power);

    els.pwrText.textContent = `${Math.round(sys.power)}%`;
    els.effText.textContent = sys.efficiency.toFixed(2);

    els.row.classList.toggle('sys-row--overclocked', sys.power > OVERCLOCK_THRESHOLD);
    els.row.classList.toggle('sys-row--offline',     sys.health <= 0);

    const needsHint = hintsEnabled && sys.health < 50 && sys.power < 75;
    els.hintBadge.style.display = needsHint ? '' : 'none';
  }

  // Budget bar
  const budgetPct = Math.min(100, (totalPower / POWER_BUDGET) * 100);
  budgetReadoutEl.textContent    = `${Math.round(totalPower)} / ${POWER_BUDGET}`;
  budgetGaugeFill.style.width    = `${budgetPct}%`;
  budgetGaugeFill.style.background = 'var(--primary)';
  budgetReadoutEl.style.color      = 'var(--text-bright)';
}

// ---------------------------------------------------------------------------
// Engineering state → DOM (reactor, battery, teams, components, log)
// ---------------------------------------------------------------------------

function applyEngState(state) {
  // --- Reactor ---
  const pg = state.power_grid || {};
  const reactorOut = Math.round(pg.reactor_output || 0);
  const reactorMax = Math.round(pg.reactor_max || 700);
  reactorReadoutEl.textContent = `${reactorOut} / ${reactorMax}`;
  const reactorPct = reactorMax > 0 ? Math.min(100, (reactorOut / reactorMax) * 100) : 0;
  reactorGaugeFill.style.width = `${reactorPct}%`;
  const reactorHealth = pg.reactor_health ?? 1;
  reactorGaugeFill.style.background = reactorHealth < 0.5 ? 'var(--system-warning)' : 'var(--primary)';

  // --- Battery ---
  const batCharge = Math.round(pg.battery_charge || 0);
  const batCap    = Math.round(pg.battery_capacity || 500);
  batteryReadoutEl.textContent = `${batCharge} / ${batCap}`;
  const batPct = batCap > 0 ? Math.min(100, (batCharge / batCap) * 100) : 0;
  batteryGaugeFill.style.width = `${batPct}%`;
  batteryGaugeFill.style.background = batPct < 20 ? 'var(--system-warning)' : 'var(--friendly)';

  // Battery mode buttons
  updateBatteryModeButtons(pg.battery_mode || 'standby');

  // --- Repair teams ---
  const teams = state.repair_teams || [];
  renderTeamCards(teams);

  // --- Repair orders queue ---
  const orders = state.repair_orders || [];
  renderRepairQueue(orders);

  // --- Component detail (if system selected) ---
  if (selectedSystem && state.systems?.[selectedSystem]) {
    renderComponentDetail(selectedSystem, state.systems[selectedSystem]);
  }

  // --- Damage log ---
  const events = state.recent_damage_events || [];
  renderDamageLog(events);

  // --- Status bar ---
  sbPowerVal.textContent   = `${reactorOut}W`;
  sbBatteryVal.textContent = `${Math.round(batPct)}%`;

  const activeTeams = teams.filter(t => t.status !== 'idle').length;
  sbTeamsVal.textContent = `${activeTeams}/${teams.length}`;

  const pri = pg.primary_bus_online !== false;
  const sec = pg.secondary_bus_online !== false;
  sbBusVal.textContent = pri && sec ? 'PRI+SEC' : pri ? 'PRI' : sec ? 'SEC' : 'NONE';
  if (!pri || !sec) sbBusVal.style.color = 'var(--system-warning)';
  else sbBusVal.style.color = '';

  const isEmergency = pg.emergency_active || false;
  sbEmergencyVal.textContent = isEmergency ? 'ACTIVE' : 'NOMINAL';
  if (sbEmergencyEl) {
    sbEmergencyEl.classList.toggle('eng-statusbar__item--emergency', isEmergency);
  }
}

// ---------------------------------------------------------------------------
// Build system control rows
// ---------------------------------------------------------------------------

function buildSystemRows() {
  systemsContainer.innerHTML = '';

  for (const def of SYSTEM_DEFS) {
    const row = document.createElement('div');
    row.className      = 'sys-row';
    row.dataset.system = def.key;

    // Click row to select system for detail
    row.addEventListener('click', (e) => {
      // Don't trigger when clicking slider or button
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON') return;
      selectSystem(def.key);
    });

    // Header
    const header = document.createElement('div');
    header.className = 'sys-row__header';

    const nameEl = document.createElement('span');
    nameEl.className   = 'sys-row__name';
    nameEl.textContent = `${def.shortKey}. ${def.label}`;

    const repairBtn = document.createElement('button');
    repairBtn.className   = 'sys-row__repair-btn';
    repairBtn.textContent = 'REPAIR';
    repairBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      selectRepair(def.key);
    });

    const hintBadge = document.createElement('span');
    hintBadge.className   = 'sys-row__hint-badge';
    hintBadge.textContent = 'RECOMMENDED';
    hintBadge.style.display = 'none';

    header.appendChild(nameEl);
    header.appendChild(hintBadge);
    header.appendChild(repairBtn);

    // Power slider
    const sliderWrap = document.createElement('div');
    sliderWrap.className = 'sys-row__slider-wrap';

    const slider = document.createElement('input');
    slider.type      = 'range';
    slider.className = 'sys-row__slider';
    slider.min       = '0';
    slider.max       = '150';
    slider.step      = '5';
    slider.value     = '100';
    slider.setAttribute('aria-label', `${def.label} power`);

    slider.addEventListener('input', () => {
      if (!gameActive) return;
      const level = parseInt(slider.value, 10);
      send('engineering.set_power', { system: def.key, level });
      updateSliderBackground(slider, level);
      row.classList.toggle('sys-row--overclocked', level > OVERCLOCK_THRESHOLD);
    });

    sliderWrap.appendChild(slider);

    // Status row
    const statusRow = document.createElement('div');
    statusRow.className = 'sys-row__status';

    const healthWrap = document.createElement('div');
    healthWrap.className = 'sys-row__health-wrap';

    const healthBar = document.createElement('div');
    healthBar.className = 'gauge sys-row__health-bar';

    const healthFill = document.createElement('div');
    healthFill.className  = 'gauge__fill';
    healthFill.style.width      = '100%';
    healthFill.style.background = C_HEALTHY;

    healthBar.appendChild(healthFill);
    healthWrap.appendChild(healthBar);

    const statsEl = document.createElement('div');
    statsEl.className = 'sys-row__stats';

    const healthText = document.createElement('span');
    healthText.className   = 'text-data';
    healthText.style.color = C_HEALTHY;
    healthText.textContent = '100%';

    const pwrText = document.createElement('span');
    pwrText.className   = 'text-data';
    pwrText.textContent = '100%';

    const effText = document.createElement('span');
    effText.className   = 'text-data';
    effText.textContent = '1.00';

    statsEl.appendChild(makeStatCol('HP',  healthText));
    statsEl.appendChild(makeStatCol('PWR', pwrText));
    statsEl.appendChild(makeStatCol('EFF', effText));

    statusRow.appendChild(healthWrap);
    statusRow.appendChild(statsEl);

    // Assemble
    row.appendChild(header);
    row.appendChild(sliderWrap);
    row.appendChild(statusRow);
    systemsContainer.appendChild(row);

    sysEls[def.key] = { row, slider, healthFill, healthText, pwrText, effText, repairBtn, hintBadge };
    updateSliderBackground(slider, 100);
  }
}

function makeStatCol(label, valueEl) {
  const col = document.createElement('div');
  col.className = 'sys-row__stat';
  const lbl = document.createElement('span');
  lbl.className   = 'text-label';
  lbl.textContent = label;
  col.appendChild(lbl);
  col.appendChild(valueEl);
  return col;
}

// ---------------------------------------------------------------------------
// Power slider visual
// ---------------------------------------------------------------------------

function updateSliderBackground(slider, value) {
  const vPct  = (value / 150) * 100;
  const oc100 = (100   / 150) * 100;

  let bg;
  if (value <= OVERCLOCK_THRESHOLD) {
    bg = [
      `var(--primary-dim) 0%`,
      `var(--primary-dim) ${vPct}%`,
      `var(--bg-secondary) ${vPct}%`,
      `var(--bg-secondary) ${oc100}%`,
      `rgba(255,176,0,0.10) ${oc100}%`,
      `rgba(255,176,0,0.10) 100%`,
    ].join(', ');
  } else {
    bg = [
      `var(--primary-dim) 0%`,
      `var(--primary-dim) ${oc100}%`,
      `rgba(255,176,0,0.55) ${oc100}%`,
      `rgba(255,176,0,0.55) ${vPct}%`,
      `var(--bg-secondary) ${vPct}%`,
      `var(--bg-secondary) 100%`,
    ].join(', ');
  }

  slider.style.background = `linear-gradient(to right, ${bg})`;
}

// ---------------------------------------------------------------------------
// Health helpers
// ---------------------------------------------------------------------------

function updateHealthDOM(key, health, els) {
  const color = systemColor(health);
  els.healthFill.style.width      = `${Math.max(0, health)}%`;
  els.healthFill.style.background = color;
  els.healthText.textContent      = `${Math.round(health)}%`;
  els.healthText.style.color      = color;
}

function updateRepairFocusDOM() {
  for (const def of SYSTEM_DEFS) {
    const els = sysEls[def.key];
    if (!els) continue;
    const active = repairFocus === def.key;
    els.row.classList.toggle('sys-row--repair-focus', active);
    els.repairBtn.classList.toggle('sys-row__repair-btn--active', active);
    els.repairBtn.textContent = active ? 'REPAIRING' : 'REPAIR';
  }
}

function systemColor(health) {
  if (health <= 0)  return C_OFFLINE;
  if (health < 30)  return C_CRITICAL;
  if (health < 60)  return C_WARNING;
  return C_HEALTHY;
}

function hexToRgb(hex) {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

// ---------------------------------------------------------------------------
// Repair selection
// ---------------------------------------------------------------------------

function selectRepair(systemKey) {
  if (!gameActive) return;
  send('engineering.set_repair', { system: systemKey });
  repairFocus = systemKey;
  updateRepairFocusDOM();
}

// ---------------------------------------------------------------------------
// System selection (for detail panel)
// ---------------------------------------------------------------------------

function selectSystem(systemKey) {
  if (!gameActive) return;

  // Toggle off if already selected
  if (selectedSystem === systemKey) {
    selectedSystem = null;
    clearDetailPanel();
    updateSelectedSystemDOM();
    return;
  }

  selectedSystem = systemKey;
  updateSelectedSystemDOM();

  // On narrow screens, show the detail panel
  const detailEl = document.querySelector('.eng-detail');
  if (detailEl) detailEl.classList.add('eng-detail--visible');

  // Render component detail from latest eng state
  if (currEngState?.systems?.[systemKey]) {
    renderComponentDetail(systemKey, currEngState.systems[systemKey]);
  } else {
    detailTitleEl.textContent = systemKey.replace(/_/g, ' ').toUpperCase();
    componentsEl.innerHTML = '<p class="text-dim eng-detail__empty">Awaiting engineering data...</p>';
  }

  // Show dispatch controls
  renderDispatchControls(systemKey);
}

function updateSelectedSystemDOM() {
  for (const def of SYSTEM_DEFS) {
    const els = sysEls[def.key];
    if (!els) continue;
    els.row.classList.toggle('sys-row--selected', selectedSystem === def.key);
  }
}

function clearDetailPanel() {
  detailTitleEl.textContent = 'SELECT A SYSTEM';
  componentsEl.innerHTML = '<p class="text-dim eng-detail__empty">Click a system or press 1-9 to select.</p>';
  dispatchControlsEl.style.display = 'none';

  const detailEl = document.querySelector('.eng-detail');
  if (detailEl) detailEl.classList.remove('eng-detail--visible');
}

// ---------------------------------------------------------------------------
// Component detail panel (right column)
// ---------------------------------------------------------------------------

function renderComponentDetail(systemKey, sysData) {
  const label = SYSTEM_DEFS.find(d => d.key === systemKey)?.label || systemKey.toUpperCase();
  detailTitleEl.textContent = label;

  const components = sysData.components || [];
  if (components.length === 0) {
    componentsEl.innerHTML = '<p class="text-dim eng-detail__empty">No component data available.</p>';
    return;
  }

  componentsEl.innerHTML = '';
  for (const comp of components) {
    const row = document.createElement('div');
    row.className = 'comp-row';

    const header = document.createElement('div');
    header.className = 'comp-row__header';

    const nameEl = document.createElement('span');
    nameEl.className   = 'comp-row__name';
    nameEl.textContent = comp.name;

    const healthVal = document.createElement('span');
    healthVal.className = 'comp-row__health-val';
    const hp = Math.round(comp.health);
    healthVal.textContent = `${hp}%`;
    healthVal.style.color = systemColor(comp.health);

    header.appendChild(nameEl);
    header.appendChild(healthVal);

    const bar = document.createElement('div');
    bar.className = 'gauge comp-row__bar';
    const fill = document.createElement('div');
    fill.className = 'gauge__fill';
    fill.style.width      = `${Math.max(0, comp.health)}%`;
    fill.style.background = systemColor(comp.health);
    bar.appendChild(fill);

    const effectEl = document.createElement('span');
    effectEl.className   = 'comp-row__effect';
    effectEl.textContent = comp.effect || '';

    row.appendChild(header);
    row.appendChild(bar);
    if (comp.effect) row.appendChild(effectEl);
    componentsEl.appendChild(row);
  }
}

// ---------------------------------------------------------------------------
// Dispatch controls (right column, below components)
// ---------------------------------------------------------------------------

function renderDispatchControls(systemKey) {
  if (!currEngState?.repair_teams) {
    dispatchControlsEl.style.display = 'none';
    return;
  }

  const teams = currEngState.repair_teams;
  const idleTeams = teams.filter(t => t.status === 'idle');

  dispatchControlsEl.style.display = '';
  dispatchTeamListEl.innerHTML = '';

  if (idleTeams.length === 0) {
    const p = document.createElement('p');
    p.className = 'text-dim';
    p.textContent = 'No idle teams available.';
    p.style.fontSize = '0.68rem';
    p.style.padding = '0.2rem 0';
    dispatchTeamListEl.appendChild(p);
    return;
  }

  for (const team of idleTeams) {
    const item = document.createElement('div');
    item.className = 'eng-dispatch__item';

    const nameEl = document.createElement('span');
    nameEl.className = 'text-data';
    nameEl.textContent = team.name;

    const btn = document.createElement('button');
    btn.className = 'eng-dispatch__btn';
    btn.textContent = 'DISPATCH';
    btn.addEventListener('click', () => {
      send('engineering.dispatch_team', { team_id: team.id, system: systemKey });
    });

    item.appendChild(nameEl);
    item.appendChild(btn);
    dispatchTeamListEl.appendChild(item);
  }
}

// ---------------------------------------------------------------------------
// Repair team cards (centre column, below map)
// ---------------------------------------------------------------------------

function renderTeamCards(teams) {
  teamCardsEl.innerHTML = '';

  if (teams.length === 0) {
    const p = document.createElement('p');
    p.className = 'text-dim';
    p.textContent = 'No repair teams assigned.';
    p.style.fontSize = '0.72rem';
    p.style.padding = '0.3rem 0';
    teamCardsEl.appendChild(p);
    return;
  }

  for (const team of teams) {
    const card = document.createElement('div');
    card.className = `team-card team-card--${team.status}`;

    const nameEl = document.createElement('div');
    nameEl.className   = 'team-card__name';
    nameEl.textContent = team.name;

    const statusEl = document.createElement('div');
    statusEl.className = 'team-card__status';
    let statusText = team.status.toUpperCase();
    if (team.target_system) statusText += ` → ${team.target_system.replace(/_/g, ' ').toUpperCase()}`;
    statusEl.textContent = statusText;

    card.appendChild(nameEl);
    card.appendChild(statusEl);

    // Progress bar for travelling/repairing
    if (team.status === 'travelling' || team.status === 'repairing') {
      const progress = team.status === 'travelling' ? team.travel_progress : team.repair_progress;
      const progWrap = document.createElement('div');
      progWrap.className = 'team-card__progress';
      const progFill = document.createElement('div');
      progFill.className = 'team-card__progress-fill';
      progFill.style.width = `${Math.round((progress || 0) * 100)}%`;
      progWrap.appendChild(progFill);
      card.appendChild(progWrap);
    }

    // Action buttons
    const actions = document.createElement('div');
    actions.className = 'team-card__actions';

    if (team.status === 'idle') {
      // Dispatch button (to selected system)
      if (selectedSystem) {
        const dispBtn = document.createElement('button');
        dispBtn.className = 'team-card__btn';
        dispBtn.textContent = 'DISPATCH';
        dispBtn.addEventListener('click', () => {
          send('engineering.dispatch_team', { team_id: team.id, system: selectedSystem });
        });
        actions.appendChild(dispBtn);
      }
    } else {
      // Recall button
      const recallBtn = document.createElement('button');
      recallBtn.className = 'team-card__btn team-card__btn--recall';
      recallBtn.textContent = 'RECALL';
      recallBtn.addEventListener('click', () => {
        send('engineering.recall_team', { team_id: team.id });
      });
      actions.appendChild(recallBtn);

      // Escort request button (if no escort already)
      if (!team.escort_squad_id) {
        const escortBtn = document.createElement('button');
        escortBtn.className = 'team-card__btn';
        escortBtn.textContent = 'ESCORT';
        escortBtn.addEventListener('click', () => {
          send('engineering.request_escort', { team_id: team.id });
        });
        actions.appendChild(escortBtn);
      }
    }

    if (actions.children.length > 0) card.appendChild(actions);
    teamCardsEl.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// Repair queue (left column, bottom)
// ---------------------------------------------------------------------------

function renderRepairQueue(orders) {
  repairQueueCountEl.textContent = orders.length;

  if (orders.length === 0) {
    repairQueueListEl.innerHTML = '<p class="text-dim eng-repair-queue__empty">No repair orders queued.</p>';
    return;
  }

  repairQueueListEl.innerHTML = '';
  for (const orderId of orders) {
    const item = document.createElement('div');
    item.className = 'eng-repair-queue__item';

    const label = document.createElement('span');
    label.className = 'text-data';
    label.textContent = orderId;

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'eng-repair-queue__cancel';
    cancelBtn.textContent = 'CANCEL';
    cancelBtn.addEventListener('click', () => {
      send('engineering.cancel_repair_order', { order_id: orderId });
    });

    item.appendChild(label);
    item.appendChild(cancelBtn);
    repairQueueListEl.appendChild(item);
  }
}

// ---------------------------------------------------------------------------
// Damage log (right column, bottom)
// ---------------------------------------------------------------------------

function renderDamageLog(events) {
  if (events.length === 0) {
    damageLogListEl.innerHTML = '<p class="text-dim" style="font-size:0.8rem;padding:0.2rem 0">No recent damage events.</p>';
    return;
  }

  damageLogListEl.innerHTML = '';
  for (const evt of events) {
    const item = document.createElement('div');
    item.className = 'eng-damage-log__item';
    const sysLabel = (evt.system || '').replace(/_/g, ' ').toUpperCase();
    const compLabel = evt.component_id || '';
    const dmg = Math.round(evt.damage || 0);
    item.textContent = `${sysLabel} / ${compLabel}: -${dmg} (${evt.cause || 'unknown'})`;
    damageLogListEl.appendChild(item);
  }
}

// ---------------------------------------------------------------------------
// Battery mode buttons
// ---------------------------------------------------------------------------

function setupBatteryModeButtons() {
  if (!batteryModesEl) return;
  batteryModesEl.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-mode]');
    if (!btn || !gameActive) return;
    const mode = btn.dataset.mode;
    send('engineering.set_battery_mode', { mode });
  });
}

function updateBatteryModeButtons(activeMode) {
  if (!batteryModesEl) return;
  for (const btn of batteryModesEl.querySelectorAll('[data-mode]')) {
    btn.classList.toggle('eng-battery__mode-btn--active', btn.dataset.mode === activeMode);
  }
}

// ---------------------------------------------------------------------------
// Overlay selector
// ---------------------------------------------------------------------------

function setupOverlayButtons() {
  if (!overlaySelectorEl) return;
  overlaySelectorEl.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-overlay]');
    if (!btn) return;
    setOverlay(btn.dataset.overlay);
  });
}

function setOverlay(mode) {
  activeOverlay = mode;
  if (!overlaySelectorEl) return;
  for (const btn of overlaySelectorEl.querySelectorAll('[data-overlay]')) {
    btn.classList.toggle('eng-overlay-btn--active', btn.dataset.overlay === mode);
  }
}

// ---------------------------------------------------------------------------
// Keyboard shortcuts
// ---------------------------------------------------------------------------

function setupKeyboard() {
  document.addEventListener('keydown', (e) => {
    if (!gameActive) return;
    // Don't capture when typing in inputs
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    // 1-9: select system
    const num = parseInt(e.key, 10);
    if (num >= 1 && num <= 9) {
      const def = SYSTEM_DEFS[num - 1];
      if (def) selectSystem(def.key);
      return;
    }

    switch (e.key.toLowerCase()) {
      case 'd': // Dispatch first idle team to selected system
        if (selectedSystem && currEngState?.repair_teams) {
          const idle = currEngState.repair_teams.find(t => t.status === 'idle');
          if (idle) send('engineering.dispatch_team', { team_id: idle.id, system: selectedSystem });
        }
        break;
      case 'r': // Recall all active teams
        if (currEngState?.repair_teams) {
          for (const t of currEngState.repair_teams) {
            if (t.status !== 'idle') send('engineering.recall_team', { team_id: t.id });
          }
        }
        break;
      case 'b': // Cycle battery mode
        if (currEngState?.power_grid) {
          const curr = currEngState.power_grid.battery_mode || 'standby';
          const idx = BATTERY_MODES.indexOf(curr);
          const next = BATTERY_MODES[(idx + 1) % BATTERY_MODES.length];
          send('engineering.set_battery_mode', { mode: next });
        }
        break;
      case 'tab': // Cycle overlay
        e.preventDefault();
        {
          const idx = OVERLAY_MODES.indexOf(activeOverlay);
          setOverlay(OVERLAY_MODES[(idx + 1) % OVERLAY_MODES.length]);
        }
        break;
    }
  });
}

// ---------------------------------------------------------------------------
// Interior map canvas
// ---------------------------------------------------------------------------

function computeCanvasSize() {
  let maxCol = 3, maxRow = 4;
  for (const room of Object.values(interiorLayout)) {
    if (room.col > maxCol) maxCol = room.col;
    if (room.row > maxRow) maxRow = room.row;
  }
  const cols = maxCol + 1;
  const rows = maxRow + 1;
  canvasW = ROOM_MARGIN * 2 + cols * (ROOM_W + ROOM_GAP) - ROOM_GAP;
  canvasH = ROOM_MARGIN * 2 + rows * (ROOM_H + ROOM_GAP) - ROOM_GAP;
}

function roomPixel(col, row) {
  return {
    x: ROOM_MARGIN + col * (ROOM_W + ROOM_GAP),
    y: ROOM_MARGIN + row * (ROOM_H + ROOM_GAP),
  };
}

function roomCenter(col, row) {
  const { x, y } = roomPixel(col, row);
  return { x: x + ROOM_W / 2, y: y + ROOM_H / 2 };
}

function renderLoop(now) {
  if (!gameActive) return;
  drawInteriorMap(now);
  requestAnimationFrame(renderLoop);
}

function drawInteriorMap(now) {
  if (!ictx) return;
  const ctx = ictx;

  // Background
  drawBackground(ctx, canvasW, canvasH);

  // Draw pipelines between rooms
  drawPipelines(ctx, now);

  // Draw rooms
  for (const [roomId, room] of Object.entries(interiorLayout)) {
    const { x, y } = roomPixel(room.col, room.row);
    const rs = roomStates[roomId];
    const roomState = rs?.state || 'normal';

    // Room fill based on overlay
    drawRoomFill(ctx, x, y, roomId, roomState, now);

    // Room border
    const borderColor = roomBorderColor(roomState);
    ctx.strokeStyle = borderColor;
    ctx.lineWidth   = 1.5;
    ctx.strokeRect(x, y, ROOM_W, ROOM_H);

    // Room name
    ctx.fillStyle    = 'rgba(0, 255, 65, 0.8)';
    ctx.font         = '13px "Share Tech Mono", monospace';
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'top';
    const label = room.name.length > 18 ? room.name.slice(0, 17) + '\u2026' : room.name;
    ctx.fillText(label, x + ROOM_W / 2, y + 8);

    // Deck sub-label
    ctx.fillStyle = 'rgba(0, 255, 65, 0.45)';
    ctx.font      = '11px "Share Tech Mono", monospace';
    ctx.fillText(room.deck.toUpperCase(), x + ROOM_W / 2, y + 24);

    // DCT progress indicator
    if (roomId in activeDcts) {
      const progress = activeDcts[roomId];
      ctx.fillStyle = 'rgba(0, 255, 65, 0.25)';
      ctx.fillRect(x + 3, y + ROOM_H - 9, (ROOM_W - 6) * progress, 6);
      ctx.strokeStyle = 'rgba(0, 255, 65, 0.4)';
      ctx.lineWidth = 0.5;
      ctx.strokeRect(x + 3, y + ROOM_H - 9, ROOM_W - 6, 6);
    }
  }

  // Draw repair team overlays
  if (activeOverlay === 'teams' || activeOverlay === 'all') {
    drawTeamOverlays(ctx, now);
  }
}

/** Return the point where a pipe from `from` to `to` meets the edge of the `from` room. */
function pipeEdgePoint(fromCol, fromRow, toCol, toRow) {
  const fc = roomCenter(fromCol, fromRow);
  const tc = roomCenter(toCol, toRow);
  const dx = tc.x - fc.x;
  const dy = tc.y - fc.y;
  const halfW = ROOM_W / 2;
  const halfH = ROOM_H / 2;

  // Determine which edge the line exits through
  if (dx === 0) {
    // Vertical
    return { x: fc.x, y: dy > 0 ? fc.y + halfH : fc.y - halfH };
  }
  if (dy === 0) {
    // Horizontal
    return { x: dx > 0 ? fc.x + halfW : fc.x - halfW, y: fc.y };
  }
  // Diagonal — clamp to nearest edge
  const slope = dy / dx;
  const edgeX = dx > 0 ? halfW : -halfW;
  const yAtEdge = edgeX * slope;
  if (Math.abs(yAtEdge) <= halfH) {
    return { x: fc.x + edgeX, y: fc.y + yAtEdge };
  }
  const edgeY = dy > 0 ? halfH : -halfH;
  return { x: fc.x + edgeY / slope, y: fc.y + edgeY };
}

function drawPipelines(ctx, now) {
  const pipes = [];
  for (const [roomId, room] of Object.entries(interiorLayout)) {
    for (const connId of (room.connections || [])) {
      if (connId < roomId) continue;
      const conn = interiorLayout[connId];
      if (!conn) continue;
      pipes.push({
        from: pipeEdgePoint(room.col, room.row, conn.col, conn.row),
        to:   pipeEdgePoint(conn.col, conn.row, room.col, room.row),
      });
    }
  }

  for (const { from, to } of pipes) {
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const len = Math.sqrt(dx * dx + dy * dy);
    if (len < 1) continue;
    // Unit normal perpendicular to the pipe
    const nx = -dy / len;
    const ny =  dx / len;

    // Layer 1: Glow
    ctx.strokeStyle = 'rgba(0, 255, 65, 0.06)';
    ctx.lineWidth = 14;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();

    // Layer 2: Inner fill
    ctx.strokeStyle = 'rgba(0, 255, 65, 0.08)';
    ctx.lineWidth = 6;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();

    // Layer 3: Outer wall lines (two parallel 1px edges)
    ctx.strokeStyle = 'rgba(0, 255, 65, 0.30)';
    ctx.lineWidth = 1;
    for (const sign of [-1, 1]) {
      const ox = nx * 3 * sign;
      const oy = ny * 3 * sign;
      ctx.beginPath();
      ctx.moveTo(from.x + ox, from.y + oy);
      ctx.lineTo(to.x + ox, to.y + oy);
      ctx.stroke();
    }

    // Layer 4: Flow ticks — animated hash marks scrolling along pipe
    const tickSpacing = 12;
    const tickLen = 3;
    const scrollOffset = (now * 0.03) % tickSpacing;
    ctx.strokeStyle = 'rgba(0, 255, 65, 0.18)';
    ctx.lineWidth = 1;
    for (let d = scrollOffset; d < len; d += tickSpacing) {
      const t = d / len;
      const px = from.x + dx * t;
      const py = from.y + dy * t;
      ctx.beginPath();
      ctx.moveTo(px - nx * tickLen, py - ny * tickLen);
      ctx.lineTo(px + nx * tickLen, py + ny * tickLen);
      ctx.stroke();
    }

    // Layer 5: Junction nodes at pipe endpoints
    ctx.fillStyle = 'rgba(0, 255, 65, 0.25)';
    for (const pt of [from, to]) {
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function drawRoomFill(ctx, x, y, roomId, roomState, now) {
  const showDamage  = activeOverlay === 'damage'  || activeOverlay === 'all';
  const showHazards = activeOverlay === 'hazards' || activeOverlay === 'all';

  // Default fill
  ctx.fillStyle = 'rgba(0, 255, 65, 0.04)';

  if (showHazards) {
    if (roomState === 'fire') {
      const pulse = 0.08 + 0.06 * Math.sin(now / 200);
      ctx.fillStyle = `rgba(255, 85, 0, ${pulse})`;
    } else if (roomState === 'decompressed') {
      ctx.fillStyle = 'rgba(0, 100, 200, 0.08)';
    }
  }

  if (showDamage && roomState === 'damaged') {
    ctx.fillStyle = 'rgba(255, 170, 0, 0.06)';
  }

  // Fire always overrides in damage mode too
  if (showDamage && roomState === 'fire') {
    const pulse = 0.08 + 0.06 * Math.sin(now / 200);
    ctx.fillStyle = `rgba(255, 85, 0, ${pulse})`;
  }

  ctx.fillRect(x, y, ROOM_W, ROOM_H);
}

function drawTeamOverlays(ctx, _now) {
  if (!currEngState?.repair_teams) return;

  for (const team of currEngState.repair_teams) {
    if (team.status === 'idle') continue;

    // Find the room where the team currently is
    const roomId = team.room_id;
    const room = roomId ? interiorLayout[roomId] : null;
    if (!room) continue;

    const center = roomCenter(room.col, room.row);

    // Team icon
    const iconR = 10;
    ctx.beginPath();
    ctx.arc(center.x, center.y + 28, iconR, 0, Math.PI * 2);

    if (team.status === 'repairing') {
      ctx.fillStyle = 'rgba(0, 255, 65, 0.3)';
      ctx.fill();
      ctx.strokeStyle = C_HEALTHY;
    } else if (team.status === 'travelling') {
      ctx.fillStyle = 'rgba(255, 176, 0, 0.3)';
      ctx.fill();
      ctx.strokeStyle = C_WARNING;
    } else {
      ctx.fillStyle = 'rgba(100, 100, 100, 0.3)';
      ctx.fill();
      ctx.strokeStyle = C_OFFLINE;
    }
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Team label
    ctx.fillStyle    = 'rgba(255, 255, 255, 0.7)';
    ctx.font         = '11px "Share Tech Mono", monospace';
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(team.name.slice(0, 3).toUpperCase(), center.x, center.y + 28);

    // Draw path line if travelling
    if (team.status === 'travelling' && team.path?.length > 0) {
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = 'rgba(255, 176, 0, 0.4)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(center.x, center.y + 28);
      for (const pathRoomId of team.path) {
        const pathRoom = interiorLayout[pathRoomId];
        if (pathRoom) {
          const pathCenter = roomCenter(pathRoom.col, pathRoom.row);
          ctx.lineTo(pathCenter.x, pathCenter.y + 28);
        }
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }
}

function roomBorderColor(state) {
  switch (state) {
    case 'fire':         return 'rgba(255, 85, 0, 0.7)';
    case 'decompressed': return 'rgba(100, 150, 200, 0.6)';
    case 'damaged':      return 'rgba(255, 170, 0, 0.6)';
    default:             return 'rgba(0, 255, 65, 0.35)';
  }
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
