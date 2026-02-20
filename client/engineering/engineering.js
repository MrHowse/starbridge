/**
 * Starbridge — Engineering Station
 *
 * Displays a top-down ship schematic with 6 system nodes and a right-side
 * panel for power allocation sliders, health bars, and repair control.
 *
 * Server messages received:
 *   ship.state         — full system snapshot (power, health, efficiency per system)
 *   ship.system_damaged — brief red flash + immediate health update for a system
 *
 * Server messages sent:
 *   engineering.set_power  { system, level } — adjust a system's power (0–150)
 *   engineering.set_repair { system }        — set repair focus to one system
 *
 * Render loop:
 *   rAF at ~60 fps drives the schematic canvas only (damage flash + repair pulse).
 *   DOM readouts (sliders, bars, text) are updated directly in the ship.state handler.
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
  { selector: '#schematic',         text: 'Ship schematic — click a system node to set repair focus.', position: 'right' },
  { selector: '#systems-container', text: 'System sliders — drag to allocate power (0–150%). Budget is 700 total.', position: 'left' },
  { selector: '#budget-readout',    text: 'Power budget — stay under 700 to avoid overload.', position: 'below' },
]);

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POWER_BUDGET        = 700;    // total budget for all 7 systems combined
const OVERCLOCK_THRESHOLD = 100;    // power above this is "overclocked"
const DAMAGE_FLASH_MS     = 500;    // duration of the red damage flash on a node

// System health colour thresholds (match STYLE_GUIDE.md --system-* variables)
const C_HEALTHY  = '#00ff41';
const C_WARNING  = '#ffb000';
const C_CRITICAL = '#ff2020';
const C_OFFLINE  = '#444444';

// ---------------------------------------------------------------------------
// System definitions
// ---------------------------------------------------------------------------

/**
 * All 6 ship systems with their normalised positions on the schematic canvas.
 * nx/ny are in the range [-0.5, 0.5]; multiplied by `scale` at render time.
 * labelDir controls where the text label appears relative to the node circle.
 */
const SYSTEM_DEFS = [
  { key: 'sensors',     label: 'SENSORS',    nx:  0.00, ny: -0.36, labelDir: 'below' },
  { key: 'shields',     label: 'SHIELDS',    nx:  0.00, ny: -0.12, labelDir: 'right' },
  { key: 'beams',       label: 'BEAMS',      nx: -0.28, ny:  0.04, labelDir: 'left'  },
  { key: 'torpedoes',   label: 'TORPEDOES',  nx:  0.28, ny:  0.04, labelDir: 'right' },
  { key: 'manoeuvring', label: 'MANOEUV.',   nx:  0.00, ny:  0.20, labelDir: 'left'  },
  { key: 'engines',     label: 'ENGINES',    nx:  0.00, ny:  0.37, labelDir: 'above' },
  { key: 'flight_deck', label: 'FLT DECK',   nx:  0.28, ny: -0.20, labelDir: 'right' },
];

/**
 * Ship hull outline — top-down view, nose pointing up (negative Y).
 * Points are normalised; multiply by scale for canvas pixels.
 */
const HULL_POINTS = [
  [ 0.00, -0.44],   // nose tip
  [-0.16, -0.30],   // fore port
  [-0.36, -0.08],   // port widest
  [-0.36,  0.18],   // port mid-aft
  [-0.26,  0.32],   // port nacelle outer
  [-0.22,  0.43],   // port engine tip
  [-0.14,  0.36],   // port nacelle inner
  [-0.06,  0.38],   // stern port
  [ 0.00,  0.44],   // stern centre
  [ 0.06,  0.38],   // stern starboard
  [ 0.14,  0.36],   // stbd nacelle inner
  [ 0.22,  0.43],   // stbd engine tip
  [ 0.26,  0.32],   // stbd nacelle outer
  [ 0.36,  0.18],   // stbd mid-aft
  [ 0.36, -0.08],   // stbd widest
  [ 0.16, -0.30],   // fore starboard
];

/**
 * Interior structural detail lines — bulkheads, spinal corridor, nacelle dividers.
 * Each entry is [[ax, ay], [bx, by]] in normalised coordinates.
 */
const STRUCTURE_LINES = [
  // Centre spine
  [[ 0.00, -0.44], [ 0.00,  0.38]],
  // Fore bulkhead (sensors ↔ shields zone)
  [[-0.14, -0.22], [ 0.14, -0.22]],
  // Mid bulkhead (beams/torpedoes zone)
  [[-0.34,  0.06], [ 0.34,  0.06]],
  // Aft bulkhead (manoeuvring zone)
  [[-0.26,  0.26], [ 0.26,  0.26]],
  // Port nacelle divider
  [[-0.14,  0.36], [-0.06,  0.38]],
  // Starboard nacelle divider
  [[ 0.14,  0.36], [ 0.06,  0.38]],
];

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusDotEl     = document.querySelector('[data-status-dot]');
const statusLabelEl   = document.querySelector('[data-status-label]');
const standbyEl       = document.querySelector('[data-standby]');
const engMainEl       = document.querySelector('[data-eng-main]');
const missionLabelEl  = document.getElementById('mission-label');
const schematicCanvas = document.getElementById('schematic');
const budgetReadoutEl = document.getElementById('budget-readout');
const budgetGaugeFill = document.getElementById('budget-gauge-fill');
const repairStatusEl  = document.getElementById('repair-status-label');
const systemsContainer = document.getElementById('systems-container');

// ---------------------------------------------------------------------------
// Game state
// ---------------------------------------------------------------------------

let gameActive    = false;
let hintsEnabled  = false;  // true when difficulty === 'cadet'
let currState     = null;   // most recent ship.state payload
let repairFocus   = null;   // key of the system currently being repaired (or null)

/**
 * Timestamp (performance.now()) of the most recent damage event per system.
 * Used to drive the red flash animation in the schematic render loop.
 */
const flashSystems = {};

/** Canvas rendering context — set on first game start after layout is ready. */
let sctx = null;

/**
 * Per-system DOM element cache, keyed by system name.
 * Populated by buildSystemRows() at game start.
 *
 * @type {Record<string, {
 *   row: HTMLElement,
 *   slider: HTMLInputElement,
 *   healthFill: HTMLElement,
 *   healthText: HTMLElement,
 *   pwrText: HTMLElement,
 *   effText: HTMLElement,
 *   repairBtn: HTMLButtonElement,
 *   hintBadge: HTMLElement,
 * }>}
 */
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
    console.log('[engineering] Connected as', payload.connection_id);
  });

  on('game.started',           handleGameStarted);
  on('ship.state',             handleShipState);
  on('ship.system_damaged',    handleSystemDamaged);
  on('ship.hull_hit',          handleHullHit);
  on('ship.alert_changed',     ({ level }) => setAlertLevel(level));
  on('game.over',              handleGameOver);
  on('puzzle.assist_available', handleAssistAvailable);
  on('puzzle.assist_sent',      handleAssistSent);
  on('engineering.dc_state',   handleDCState);
  on('captain.override_changed', handleCaptainOverride);

  initPuzzleRenderer(send);
  setupSchematicClick();
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

  // Build the system rows synchronously so they are ready before the first
  // ship.state tick arrives (the game loop starts broadcasting immediately).
  buildSystemRows();
  gameActive = true;

  // Defer canvas setup one frame so the grid layout is fully computed
  // before we read clientWidth/clientHeight for sizing.
  requestAnimationFrame(() => {
    sctx = schematicCanvas.getContext('2d');
    resizeSchematic();
    window.addEventListener('resize', resizeSchematic);
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
  currState = payload;
  applyState(payload);
  const totalPwr = Object.values(payload.systems || {}).reduce((s, sys) => s + (sys.power || 0), 0);
  SoundBank.setAmbient('reactor_drone', { powerLoad: totalPwr / POWER_BUDGET });
}

/**
 * Hull took damage from an incoming hit — flash the station border red.
 */
function handleHullHit() {
  SoundBank.play('hull_hit');
  const el = document.querySelector('.station-container') || document.body;
  el.style.transition = 'outline 0.05s ease';
  el.style.outline    = '3px solid #ff2020';
  setTimeout(() => { el.style.outline = ''; }, 500);
}

// ---------------------------------------------------------------------------
// Cross-station assist notification panel
// ---------------------------------------------------------------------------

/** The floating assist notification element, or null when not shown. */
let _assistPanel = null;

/**
 * Science has an active frequency puzzle that Engineering can assist.
 * Show a notification panel instructing the engineer to boost sensor power.
 */
function handleAssistAvailable(payload) {
  // Remove any previous notification.
  if (_assistPanel) _assistPanel.remove();

  const panel = document.createElement('div');
  panel.className = 'assist-panel panel';
  panel.innerHTML = `
    <div class="panel__header">
      <span class="text-label">⚡ SENSOR ASSIST AVAILABLE</span>
    </div>
    <p class="assist-panel__msg text-data">${payload.instructions}</p>
  `;
  const container = document.querySelector('.station-container');
  if (container) container.appendChild(panel);
  _assistPanel = panel;
}

/**
 * The sensor assist was applied — update the notification to confirm relay.
 */
function handleAssistSent(payload) {
  if (!_assistPanel) return;
  const msgEl = _assistPanel.querySelector('.assist-panel__msg');
  if (msgEl) {
    msgEl.textContent = payload.message || 'Calibration data relayed to Science.';
    msgEl.classList.add('assist-panel__msg--sent');
  }
  // Auto-dismiss after 4 s.
  setTimeout(() => {
    if (_assistPanel) {
      _assistPanel.remove();
      _assistPanel = null;
    }
  }, 4000);
}

/**
 * A system took damage (from overclock or combat). Flash the node on the
 * schematic and update the health bar immediately without waiting for the
 * next ship.state tick.
 */
function handleSystemDamaged(payload) {
  SoundBank.play('system_damage');
  flashSystems[payload.system] = performance.now();

  // Optimistically update health so the bar reflects damage instantly.
  if (currState?.systems?.[payload.system] != null) {
    currState.systems[payload.system].health = payload.new_health;
  }
  const els = sysEls[payload.system];
  if (els) {
    updateHealthDOM(payload.system, payload.new_health, els);
  }
}

// ---------------------------------------------------------------------------
// State → DOM
// ---------------------------------------------------------------------------

/**
 * Apply a full ship.state payload to all DOM elements in the controls panel.
 * Called on every server tick (10 Hz); canvas is updated separately via rAF.
 */
function applyState(state) {
  if (state.alert_level) setAlertLevel(state.alert_level);

  // Repair focus may have changed (e.g. server corrected our optimistic update).
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

    // Reflect server-clamped power on slider (user may have dragged beyond budget).
    const serverPwr = Math.round(sys.power);
    if (parseInt(els.slider.value, 10) !== serverPwr) {
      els.slider.value = serverPwr;
    }
    updateSliderBackground(els.slider, sys.power);

    els.pwrText.textContent = `${Math.round(sys.power)}%`;
    els.effText.textContent = sys.efficiency.toFixed(2);

    // Overclock indicator on row + slider thumb colour.
    els.row.classList.toggle('sys-row--overclocked', sys.power > OVERCLOCK_THRESHOLD);
    els.row.classList.toggle('sys-row--offline',     sys.health <= 0);

    // Cadet hint: flag critical systems (health < 50%) that are underpowered (< 75%).
    const needsHint = hintsEnabled && sys.health < 50 && sys.power < 75;
    els.hintBadge.style.display = needsHint ? '' : 'none';
  }

  // Budget bar
  const budgetPct = Math.min(100, (totalPower / POWER_BUDGET) * 100);
  budgetReadoutEl.textContent    = `${Math.round(totalPower)} / ${POWER_BUDGET}`;
  budgetGaugeFill.style.width    = `${budgetPct}%`;

  // Budget bar is informational only — always green.
  // 600/600 is the comfortable starting equilibrium, not a warning state.
  // Per-system overclock warnings (amber slider thumb, sys-row--overclocked) handle alerts.
  budgetGaugeFill.style.background = 'var(--primary)';
  budgetReadoutEl.style.color       = 'var(--text-bright)';
}

/** Update a system's health bar and readout text. */
function updateHealthDOM(key, health, els) {
  const color = systemColor(health);
  els.healthFill.style.width      = `${Math.max(0, health)}%`;
  els.healthFill.style.background = color;
  els.healthText.textContent      = `${Math.round(health)}%`;
  els.healthText.style.color      = color;
}

/** Refresh all repair-focus indicators across the controls panel. */
function updateRepairFocusDOM() {
  for (const def of SYSTEM_DEFS) {
    const els = sysEls[def.key];
    if (!els) continue;
    const active = repairFocus === def.key;
    els.row.classList.toggle('sys-row--repair-focus', active);
    els.repairBtn.classList.toggle('sys-row__repair-btn--active', active);
    els.repairBtn.textContent = active ? 'REPAIRING' : 'REPAIR';
  }
  repairStatusEl.textContent = repairFocus
    ? `REPAIRING: ${repairFocus.toUpperCase()}`
    : 'NO REPAIR ACTIVE';
}

// ---------------------------------------------------------------------------
// Build system control rows
// ---------------------------------------------------------------------------

/**
 * Dynamically create all 6 system rows and append them to systemsContainer.
 * Called once at game start (synchronously, before gameActive = true).
 */
function buildSystemRows() {
  systemsContainer.innerHTML = '';

  for (const def of SYSTEM_DEFS) {

    // ── Row container ────────────────────────────────────────────────────
    const row = document.createElement('div');
    row.className      = 'sys-row';
    row.dataset.system = def.key;

    // ── Header: name + repair button ────────────────────────────────────
    const header = document.createElement('div');
    header.className = 'sys-row__header';

    const nameEl = document.createElement('span');
    nameEl.className   = 'sys-row__name';
    nameEl.textContent = def.label;

    const repairBtn = document.createElement('button');
    repairBtn.className   = 'sys-row__repair-btn';
    repairBtn.textContent = 'REPAIR';
    repairBtn.addEventListener('click', () => selectRepair(def.key));

    // Cadet hint badge — shown when system is damaged and underpowered.
    const hintBadge = document.createElement('span');
    hintBadge.className   = 'sys-row__hint-badge';
    hintBadge.textContent = 'RECOMMENDED';
    hintBadge.style.display = 'none';

    header.appendChild(nameEl);
    header.appendChild(hintBadge);
    header.appendChild(repairBtn);

    // ── Power slider ─────────────────────────────────────────────────────
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
      // Optimistic overclock class — server will confirm next tick.
      row.classList.toggle('sys-row--overclocked', level > OVERCLOCK_THRESHOLD);
    });

    sliderWrap.appendChild(slider);

    // ── Status row: health bar + stat columns ────────────────────────────
    const statusRow = document.createElement('div');
    statusRow.className = 'sys-row__status';

    // Health bar
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

    // Stat columns — HP / PWR / EFF
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

    // ── Assemble row ─────────────────────────────────────────────────────
    row.appendChild(header);
    row.appendChild(sliderWrap);
    row.appendChild(statusRow);
    systemsContainer.appendChild(row);

    // Cache element refs for fast access in update loops.
    sysEls[def.key] = { row, slider, healthFill, healthText, pwrText, effText, repairBtn, hintBadge };

    // Set initial slider gradient.
    updateSliderBackground(slider, 100);
  }
}

/** Helper — make a labelled stat column (label above, value below). */
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

/**
 * Set the slider's track gradient to show:
 *   0 → value     : primary-dim fill (or amber if overclocked)
 *   100% threshold : amber warning marker zone (subtle when normal, bright when OC)
 *   value → 150%   : dark unfilled track
 */
function updateSliderBackground(slider, value) {
  const vPct   = (value / 150) * 100;      // slider value as % of full range
  const oc100  = (100   / 150) * 100;      // 66.67% — the overclock threshold

  let bg;
  if (value <= OVERCLOCK_THRESHOLD) {
    // Normal range: green fill up to value, then a subtle amber hint beyond.
    bg = [
      `var(--primary-dim) 0%`,
      `var(--primary-dim) ${vPct}%`,
      `var(--bg-secondary) ${vPct}%`,
      `var(--bg-secondary) ${oc100}%`,
      `rgba(255,176,0,0.10) ${oc100}%`,
      `rgba(255,176,0,0.10) 100%`,
    ].join(', ');
  } else {
    // Overclocked: green fill to 100%, amber from 100% to value, dark beyond.
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
// Repair selection
// ---------------------------------------------------------------------------

/** Send an engineering.set_repair message and optimistically update the UI. */
function selectRepair(systemKey) {
  if (!gameActive) return;
  send('engineering.set_repair', { system: systemKey });
  repairFocus = systemKey;
  updateRepairFocusDOM();
}

// ---------------------------------------------------------------------------
// Schematic canvas
// ---------------------------------------------------------------------------

/**
 * Schematic click — hit-test each system node and select it as repair target.
 * Registered once in init(); gameActive guard prevents premature activation.
 */
function setupSchematicClick() {
  schematicCanvas.addEventListener('click', (e) => {
    if (!gameActive || !sctx) return;

    const rect   = schematicCanvas.getBoundingClientRect();
    const scaleX = schematicCanvas.width  / rect.width;
    const scaleY = schematicCanvas.height / rect.height;
    const mx     = (e.clientX - rect.left) * scaleX;
    const my     = (e.clientY - rect.top)  * scaleY;

    const { cx, cy, scale } = schematicMetrics();
    const nodeR  = computeNodeRadius(scale);
    const hitR   = nodeR * 1.8;   // slightly generous hit area

    for (const def of SYSTEM_DEFS) {
      const sx = cx + def.nx * scale;
      const sy = cy + def.ny * scale;
      const dx = mx - sx;
      const dy = my - sy;
      if (dx * dx + dy * dy <= hitR * hitR) {
        selectRepair(def.key);
        return;
      }
    }
  });
}

/**
 * Resize the schematic canvas pixel buffer to match its CSS layout size.
 * Called on game start and on window resize.
 */
function resizeSchematic() {
  const wrap = schematicCanvas.parentElement;
  schematicCanvas.width  = wrap.clientWidth;
  schematicCanvas.height = wrap.clientHeight;
}

/** rAF-driven render loop — only runs while game is active. */
function renderLoop(now) {
  if (!gameActive) return;
  drawSchematic(now);
  requestAnimationFrame(renderLoop);
}

/**
 * Compute the shared centre + scale values used by both the renderer and the
 * click handler (so they stay in sync as canvas size changes).
 */
function schematicMetrics() {
  const w  = schematicCanvas.width;
  const h  = schematicCanvas.height;
  // Scale so the ship fills ~88% of the smaller dimension with equal padding.
  const scale = Math.min(w * 0.40, h * 0.44);
  return { cx: w / 2, cy: h / 2, scale, w, h };
}

/** Node radius scaled to the canvas. */
function computeNodeRadius(scale) {
  return Math.max(13, Math.round(scale * 0.095));
}

// ---------------------------------------------------------------------------
// Schematic drawing
// ---------------------------------------------------------------------------

/**
 * Draw the full ship schematic for one frame.
 *
 * Render order:
 *   1. Background fill
 *   2. Grid
 *   3. Hull wireframe outline
 *   4. Interior structural lines
 *   5. System nodes (health-coloured, with damage flashes + repair pulse)
 *   6. Ship ID label
 */
function drawSchematic(now) {
  if (!sctx) return;

  const ctx  = sctx;
  const { cx, cy, scale, w, h } = schematicMetrics();

  drawBackground(ctx, w, h);
  drawSchematicGrid(ctx, w, h);
  drawHull(ctx, cx, cy, scale);
  drawStructure(ctx, cx, cy, scale);
  drawSystemNodes(ctx, cx, cy, scale, now);

  // Faint identifier in corner
  ctx.fillStyle    = 'rgba(0, 255, 65, 0.18)';
  ctx.font         = '9px "Share Tech Mono", monospace';
  ctx.textAlign    = 'right';
  ctx.textBaseline = 'top';
  ctx.fillText('TSS ENDEAVOUR — ENGINEERING DIAGNOSTIC', w - 8, 6);
}

/** Draw a faint orthographic grid on the schematic background. */
function drawSchematicGrid(ctx, w, h) {
  const spacing = Math.round(Math.min(w, h) / 14);
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
  ctx.lineWidth   = 0.5;
  for (let x = spacing; x < w; x += spacing) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
  for (let y = spacing; y < h; y += spacing) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
}

/** Draw the ship hull wireframe polygon. */
function drawHull(ctx, cx, cy, scale) {
  ctx.strokeStyle = 'rgba(0, 255, 65, 0.38)';
  ctx.lineWidth   = 1.5;
  ctx.beginPath();
  HULL_POINTS.forEach(([nx, ny], i) => {
    const px = cx + nx * scale;
    const py = cy + ny * scale;
    if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  });
  ctx.closePath();
  ctx.stroke();
}

/** Draw interior structural lines (bulkheads, spine, nacelle dividers). */
function drawStructure(ctx, cx, cy, scale) {
  ctx.strokeStyle = 'rgba(0, 255, 65, 0.11)';
  ctx.lineWidth   = 0.75;
  for (const [[ax, ay], [bx, by]] of STRUCTURE_LINES) {
    ctx.beginPath();
    ctx.moveTo(cx + ax * scale, cy + ay * scale);
    ctx.lineTo(cx + bx * scale, cy + by * scale);
    ctx.stroke();
  }
}

/**
 * Draw all 6 system nodes, applying:
 *   - Health-based colour (healthy/warning/critical/offline)
 *   - Damage flash: expanding red halo that fades over DAMAGE_FLASH_MS
 *   - Repair glow: pulsing green ring around the active repair target
 *   - Health percentage label inside the node
 *   - System name label positioned to avoid overlaps
 */
function drawSystemNodes(ctx, cx, cy, scale, now) {
  const nodeR = computeNodeRadius(scale);

  for (const def of SYSTEM_DEFS) {
    const sx = cx + def.nx * scale;
    const sy = cy + def.ny * scale;

    const sys      = currState?.systems?.[def.key];
    const health   = sys?.health  ?? 100;
    const color    = systemColor(health);
    const isRepair = repairFocus === def.key;

    // ── Damage flash ──────────────────────────────────────────────────────
    const flashAge = now - (flashSystems[def.key] ?? -Infinity);
    if (flashAge >= 0 && flashAge < DAMAGE_FLASH_MS) {
      const alpha = (1 - flashAge / DAMAGE_FLASH_MS) * 0.65;
      ctx.fillStyle = `rgba(255, 32, 32, ${alpha})`;
      ctx.beginPath();
      ctx.arc(sx, sy, nodeR * 2.4, 0, Math.PI * 2);
      ctx.fill();
    }

    // ── Repair glow pulse ─────────────────────────────────────────────────
    if (isRepair) {
      const pulse     = 0.5 + 0.5 * Math.sin(now / 280);
      const glowR     = nodeR + 5 + pulse * 5;
      const glowAlpha = 0.25 + pulse * 0.40;
      ctx.strokeStyle = `rgba(0, 255, 65, ${glowAlpha})`;
      ctx.lineWidth   = 2.5;
      ctx.beginPath();
      ctx.arc(sx, sy, glowR, 0, Math.PI * 2);
      ctx.stroke();
    }

    // ── Node background fill ──────────────────────────────────────────────
    const [r, g, b]  = hexToRgb(color);
    const fillAlpha  = health <= 0 ? 0.04 : 0.12;
    ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${fillAlpha})`;
    ctx.beginPath();
    ctx.arc(sx, sy, nodeR, 0, Math.PI * 2);
    ctx.fill();

    // ── Node border ───────────────────────────────────────────────────────
    ctx.strokeStyle = color;
    ctx.lineWidth   = isRepair ? 2.5 : 1.5;
    ctx.beginPath();
    ctx.arc(sx, sy, nodeR, 0, Math.PI * 2);
    ctx.stroke();

    // ── Health value inside node ──────────────────────────────────────────
    const innerFont = Math.max(8, Math.round(nodeR * 0.60));
    ctx.fillStyle    = color;
    ctx.font         = `${innerFont}px "Share Tech Mono", monospace`;
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(health <= 0 ? 'OFF' : `${Math.round(health)}`, sx, sy);

    // ── System name label ─────────────────────────────────────────────────
    const labelFont  = Math.max(7, Math.round(nodeR * 0.50));
    const labelAlpha = isRepair ? 0.95 : 0.60;
    ctx.font         = `${labelFont}px "Share Tech Mono", monospace`;
    ctx.fillStyle    = `rgba(0, 255, 65, ${labelAlpha})`;

    const gap = nodeR + 7;
    switch (def.labelDir) {
      case 'above':
        ctx.textAlign    = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText(def.label, sx, sy - gap);
        break;
      case 'below':
        ctx.textAlign    = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(def.label, sx, sy + gap);
        break;
      case 'left':
        ctx.textAlign    = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(def.label, sx - gap, sy);
        break;
      case 'right':
        ctx.textAlign    = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillText(def.label, sx + gap, sy);
        break;
    }
  }
}

// ---------------------------------------------------------------------------
// Colour helpers
// ---------------------------------------------------------------------------

/** Map a system health value to a CSS colour constant. */
function systemColor(health) {
  if (health <= 0)  return C_OFFLINE;
  if (health < 30)  return C_CRITICAL;
  if (health < 60)  return C_WARNING;
  return C_HEALTHY;
}

/**
 * Convert a #rrggbb hex colour to an [r, g, b] number array.
 * Only called with the four C_* constants above, all of which are 6-digit hex.
 */
function hexToRgb(hex) {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

// ---------------------------------------------------------------------------
// Damage Control panel
// ---------------------------------------------------------------------------

const dcRoomListEl = document.getElementById('dc-room-list');
const dcStatusEl   = document.getElementById('dc-status');

/**
 * Handle an engineering.dc_state broadcast from the server.
 * Payload: { rooms: {room_id: {name, state, deck}}, active_dcts: {room_id: 0..1} }
 */
function handleDCState(payload) {
  if (!gameActive) return;
  renderDCPanel(payload.rooms || {}, payload.active_dcts || {});
}

/**
 * Captain system override — highlight the affected system row with a lock
 * badge so the engineering officer knows the Captain has taken it offline.
 */
function handleCaptainOverride({ system, online }) {
  const els = sysEls[system];
  if (!els) return;

  els.row.classList.toggle('sys-row--override', !online);

  // Add or remove the lock badge
  let badge = els.row.querySelector('.sys-row__override-badge');
  if (!online) {
    if (!badge) {
      badge = document.createElement('span');
      badge.className   = 'sys-row__override-badge';
      badge.textContent = '🔒 OFFLINE';
      els.row.appendChild(badge);
    }
    if (els.slider) els.slider.disabled = true;
  } else {
    if (badge) badge.remove();
    if (els.slider) els.slider.disabled = false;
  }
}

/**
 * Rebuild the damage-control room list.
 *
 * Each non-normal room gets a row with: name | state badge | [progress bar] | DISPATCH/CANCEL
 * Decompressed rooms are shown without a button (cannot be repaired by DCT).
 */
function renderDCPanel(rooms, activeDcts) {
  if (!dcRoomListEl || !dcStatusEl) return;

  const roomIds = Object.keys(rooms);
  const alertCount = roomIds.length;

  if (alertCount === 0) {
    dcStatusEl.textContent = 'ALL CLEAR';
    dcStatusEl.style.color = '';
    dcRoomListEl.innerHTML = '<p class="text-dim dc-all-clear">All compartments nominal.</p>';
    return;
  }

  dcStatusEl.textContent = `${alertCount} ALERT${alertCount > 1 ? 'S' : ''}`;
  dcStatusEl.style.color = alertCount > 0 ? '#ff5500' : '';

  dcRoomListEl.innerHTML = '';
  for (const [roomId, info] of Object.entries(rooms)) {
    const isActive = roomId in activeDcts;
    const progress = isActive ? activeDcts[roomId] : 0;
    const canRepair = info.state !== 'decompressed';

    const row = document.createElement('div');
    row.className = 'dc-room-row';

    // Room name
    const nameEl = document.createElement('span');
    nameEl.className = 'dc-room-name';
    nameEl.textContent = info.name;
    row.appendChild(nameEl);

    // State badge
    const badge = document.createElement('span');
    badge.className = `dc-state-badge dc-state-badge--${info.state}`;
    badge.textContent = info.state.toUpperCase();
    row.appendChild(badge);

    // Progress bar (only when DCT is active)
    if (isActive) {
      const wrap = document.createElement('div');
      wrap.className = 'dc-progress-wrap';
      const fill = document.createElement('div');
      fill.className = 'dc-progress-fill';
      fill.style.width = `${Math.round(progress * 100)}%`;
      wrap.appendChild(fill);
      row.appendChild(wrap);
    }

    // DISPATCH / CANCEL button (not for decompressed rooms)
    if (canRepair) {
      const btn = document.createElement('button');
      btn.className = `dc-btn${isActive ? ' dc-btn--active' : ''}`;
      btn.textContent = isActive ? 'CANCEL' : 'DISPATCH';
      btn.addEventListener('click', () => {
        if (isActive) {
          send('engineering.cancel_dct', { room_id: roomId });
        } else {
          send('engineering.dispatch_dct', { room_id: roomId });
        }
      });
      row.appendChild(btn);
    }

    dcRoomListEl.appendChild(row);
  }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
