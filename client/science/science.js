/**
 * Starbridge — Science Station
 *
 * Long-range sensor display, contact selection, and active scan interface.
 * Canvas is North-up — ship at centre with actual heading shown on chevron.
 *
 * Server messages received:
 *   game.started                  — show science UI, init canvas; payload includes
 *                                   optional signal_location for Mission 3
 *   ship.state                    — position, heading, sensor system state
 *   sensor.contacts               — range-filtered, scan-state-aware contact list
 *   science.scan_progress         — { entity_id, progress } — updates progress bar
 *   science.scan_complete         — { entity_id, results }  — shows results panel
 *   science.sector_scan_progress  — { active, scale, mode, progress, phase, elapsed,
 *                                     duration } — sector/long-range sweep progress
 *   science.sector_scan_complete  — { scale, mode, sector_id } — sweep finished
 *   science.scan_interrupted      — { reason } — combat interrupt, awaiting response
 *   mission.signal_bearing        — { bearing, scan_count, ship_x, ship_y } —
 *                                   triangulation bearing line from a scan position
 *   ship.hull_hit                 — hit-flash border
 *   game.over                     — defeat/victory overlay
 *
 * Server messages sent:
 *   lobby.claim_role              { role: 'science', player_name }
 *   science.start_scan            { entity_id }
 *   science.cancel_scan           {}
 *   science.start_sector_scan     { scale, mode }
 *   science.cancel_sector_scan    {}
 *   science.scan_interrupt_response { continue_scan }
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

const BASE_SENSOR_RANGE = 100_000;  // world units; full sector view
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
// Scan mode definitions
// ---------------------------------------------------------------------------

/**
 * rangeScale — multiplier applied to the base sensor range in this mode.
 * GRAV: mass-signature falloff is steeper, 90% effective range.
 * BIO:  life-signs attenuate through hull plating, 75% effective range.
 * SUB:  subspace horizon is wider, 125% effective range.
 *
 * filterContacts() — which contacts are detectable in this mode.
 *   EM   — all contacts.
 *   GRAV — heavy ships only (cruiser/destroyer have enough mass).
 *   BIO  — only already-scanned contacts (bio-lock needs initial EM contact).
 *   SUB  — all contacts (same as EM but through interference/cloak).
 */
const SCAN_MODES = {
  em:   { label: 'EM',   fullName: 'ELECTROMAGNETIC', key: '1', rangeScale: 1.00, color: '#00ff41' },
  grav: { label: 'GRAV', fullName: 'GRAVIMETRIC',     key: '2', rangeScale: 0.90, color: '#00aaff' },
  bio:  { label: 'BIO',  fullName: 'BIOLOGICAL',      key: '3', rangeScale: 0.75, color: '#ff44ff' },
  sub:  { label: 'SUB',  fullName: 'SUBSPACE',        key: '4', rangeScale: 1.25, color: '#aa44ff' },
};

const MODE_SWITCH_MS = 3000;  // recalibration delay (ms)

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
const resShieldFreqRow   = document.getElementById('res-shield-freq-row');
const resShieldFreq      = document.getElementById('res-shield-freq');

const sensorPowerEl = document.getElementById('sensor-power');
const sensorEffEl   = document.getElementById('sensor-efficiency');

const modeBtnEls = {
  em:   document.getElementById('mode-em'),
  grav: document.getElementById('mode-grav'),
  bio:  document.getElementById('mode-bio'),
  sub:  document.getElementById('mode-sub'),
};

const scaleBtns = {
  targeted:  document.getElementById('scale-targeted'),
  sector:    document.getElementById('scale-sector'),
  longrange: document.getElementById('scale-longrange'),
};

const interruptOverlayEl = document.getElementById('scan-interrupt-overlay');
const scanContinueBtn    = document.getElementById('scan-continue-btn');
const scanAbortBtn       = document.getElementById('scan-abort-btn');

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

// Scan mode state
let scanMode         = 'em';   // active mode: 'em' | 'grav' | 'bio' | 'sub'
let modeSwitchTarget = null;   // mode we're recalibrating to, or null
let modeSwitchStart  = 0;      // performance.now() when recalibration began

// Sector scan state (v0.05d)
let scanScale          = 'targeted'; // 'targeted' | 'sector' | 'long_range'
let sectorScanActive   = false;
let sectorScanProgress = 0;          // 0–100
let sectorScanPhase    = 0;          // 0–3
let sectorScanDuration = 45;         // seconds (from server)

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

  on('game.started',                   handleGameStarted);
  on('ship.state',                     handleShipState);
  on('ship.alert_changed',             ({ level }) => setAlertLevel(level));
  on('sensor.contacts',                handleSensorContacts);
  on('science.scan_progress',          handleScanProgress);
  on('science.scan_complete',          handleScanComplete);
  on('science.sector_scan_progress',   handleSectorScanProgress);
  on('science.sector_scan_complete',   handleSectorScanComplete);
  on('science.scan_interrupted',       handleScanInterrupted);
  on('mission.signal_bearing',         handleSignalBearing);
  on('ship.hull_hit',                  handleHullHit);
  on('game.over',                      handleGameOver);

  initPuzzleRenderer(send);
  setupControls();
  setupModeButtons();
  setupScaleButtons();
  document.addEventListener('keydown', (e) => {
    if (!gameActive) return;
    const modeByKey = { '1': 'em', '2': 'grav', '3': 'bio', '4': 'sub' };
    const m = modeByKey[e.key];
    if (m) requestModeSwitch(m);
  });
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

  // Reset scan mode.
  scanMode         = 'em';
  modeSwitchTarget = null;
  updateModeSelectorUI();

  // Reset sector scan state.
  sectorScanActive   = false;
  sectorScanProgress = 0;
  sectorScanPhase    = 0;
  scanScale          = 'targeted';
  updateScaleSelectorUI();
  if (interruptOverlayEl) interruptOverlayEl.style.display = 'none';

  requestAnimationFrame(() => {
    sensorRenderer = new MapRenderer(sensorCanvas, {
      range:         sensorRange,
      orientation:   'north-up',
      showGrid:      false,
      showRangeRings: true,
      interactive:   true,
      zoom:          { enabled: true },
      drawContact:   (ctx, sx, sy, contact, selected, _now) => {
        // Callback references module-level scanMode, so mode colour updates live.
        const modeColor = SCAN_MODES[scanMode].color;
        if (contact.scan_state === 'scanned') {
          drawScannedContact(ctx, sx, sy, contact.type, selected, modeColor);
        } else {
          drawUnknownContact(ctx, sx, sy, selected, modeColor);
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
    sensorRenderer._range = sensorRange * SCAN_MODES[scanMode].rangeScale;
    sensorRenderer.updateShipState(payload);
  }

  // Update sensor status panel.
  const power = payload.systems?.sensors?.power ?? 0;
  sensorPowerEl.textContent = `${Math.round(power)}%`;
  sensorEffEl.textContent   = `${Math.round(sensorEff * 100)}%`;

  updateRangeLabel();
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

  if (sensorRenderer) sensorRenderer.updateContacts(filterContactsForMode(contacts));

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

  if (r.shield_frequency && resShieldFreqRow && resShieldFreq) {
    resShieldFreqRow.style.display = '';
    resShieldFreq.textContent      = r.shield_frequency.toUpperCase();
  } else if (resShieldFreqRow) {
    resShieldFreqRow.style.display = 'none';
  }

  console.log(`[science] Scan complete: ${payload.entity_id}`);
}

function handleSectorScanProgress(payload) {
  if (!gameActive) return;
  sectorScanActive   = payload.active ?? true;
  sectorScanProgress = payload.progress ?? 0;
  sectorScanPhase    = payload.phase ?? 0;
  sectorScanDuration = payload.duration ?? 45;

  // Mirror progress into the existing scan bar.
  const pct = Math.min(100, Math.max(0, sectorScanProgress));
  scanProgressFill.style.width = `${pct}%`;
  scanProgressPct.textContent  = `${Math.round(pct)}%`;
  cancelBtn.disabled           = false;

  const scaleLabel = payload.scale === 'sector' ? 'SECTOR SWEEP' : 'LONG-RANGE SCAN';
  scanTargetLabel.textContent = `${scaleLabel}: ${Math.round(pct)}%`;
}

function handleSectorScanComplete(payload) {
  if (!gameActive) return;
  SoundBank.play('scan_complete');
  sectorScanActive   = false;
  sectorScanProgress = 100;

  // Show 100% briefly, then reset.
  scanProgressFill.style.width = '100%';
  scanProgressPct.textContent  = '100%';
  const scaleLabel = payload.scale === 'sector' ? 'SECTOR SWEEP' : 'LONG-RANGE SCAN';
  scanTargetLabel.textContent = `${scaleLabel}: COMPLETE`;

  if (interruptOverlayEl) interruptOverlayEl.style.display = 'none';

  setTimeout(() => {
    sectorScanProgress = 0;
    sectorScanPhase    = 0;
    scanScale          = 'targeted';
    updateScaleSelectorUI();
    resetScanProgress();
  }, 1500);

  console.log(`[science] Sector scan complete: ${payload.scale} mode=${payload.mode}`);
}

function handleScanInterrupted(_payload) {
  if (!gameActive) return;
  sectorScanActive = false;
  cancelBtn.disabled = true;
  if (interruptOverlayEl) interruptOverlayEl.style.display = '';
  console.log('[science] Scan interrupted — awaiting response');
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
    if (!gameActive) return;

    // Sector-scale scans don't require a selected contact.
    if (scanScale === 'sector' || scanScale === 'long_range') {
      send('science.start_sector_scan', { scale: scanScale, mode: scanMode });
      sectorScanActive   = true;
      sectorScanProgress = 0;
      sectorScanPhase    = 0;
      const scaleLabel = scanScale === 'sector' ? 'SECTOR SWEEP' : 'LONG-RANGE SCAN';
      scanTargetLabel.textContent = `${scaleLabel}: 0%`;
      scanBtn.disabled   = true;
      cancelBtn.disabled = false;
      updateScaleSelectorUI();
      return;
    }

    // Targeted entity scan (existing behaviour).
    if (!selectedId) return;
    send('science.start_scan', { entity_id: selectedId });
    if (selectedId === 'signal') {
      // Signal scan is instant — server replies with mission.signal_bearing, no progress.
      // Don't set scanningId; just disable briefly to prevent rapid double-tap.
      scanBtn.disabled = true;
      setTimeout(() => { if (gameActive) { scanBtn.disabled = false; } }, 800);
    } else {
      scanningId = selectedId;
      scanTargetLabel.textContent = `SCANNING: ${selectedId.toUpperCase()}`;
      scanBtn.disabled   = true;
      cancelBtn.disabled = false;
    }
  });

  cancelBtn.addEventListener('click', () => {
    if (!gameActive) return;
    if (sectorScanActive) {
      send('science.cancel_sector_scan', {});
      sectorScanActive   = false;
      sectorScanProgress = 0;
      sectorScanPhase    = 0;
      scanScale          = 'targeted';
      if (interruptOverlayEl) interruptOverlayEl.style.display = 'none';
      updateScaleSelectorUI();
      resetScanProgress();
    } else {
      send('science.cancel_scan', {});
      scanningId = null;
      resetScanProgress();
    }
  });

  // Interrupt overlay — player chooses to continue or abort after combat interrupt.
  if (scanContinueBtn) {
    scanContinueBtn.addEventListener('click', () => {
      if (!gameActive) return;
      send('science.scan_interrupt_response', { continue_scan: true });
      sectorScanActive   = true;
      cancelBtn.disabled = false;
      if (interruptOverlayEl) interruptOverlayEl.style.display = 'none';
    });
  }

  if (scanAbortBtn) {
    scanAbortBtn.addEventListener('click', () => {
      if (!gameActive) return;
      send('science.scan_interrupt_response', { continue_scan: false });
      send('science.cancel_sector_scan', {});
      sectorScanActive   = false;
      sectorScanProgress = 0;
      sectorScanPhase    = 0;
      scanScale          = 'targeted';
      if (interruptOverlayEl) interruptOverlayEl.style.display = 'none';
      updateScaleSelectorUI();
      resetScanProgress();
    });
  }
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
  // Build display list: mode-filtered real contacts + optional signal pseudo-contact.
  // Signal is an EM/electromagnetic & subspace phenomenon — not visible in GRAV or BIO.
  const displayContacts = [...filterContactsForMode(contacts)];
  if (signalLocation && signalScanCount < 2 && (scanMode === 'em' || scanMode === 'sub')) {
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
  // During sector scan, targeted controls are locked.
  if (sectorScanActive) {
    scanBtn.disabled = true;
    return;
  }

  // Sector or long-range scale selected — no contact needed.
  if (scanScale === 'sector') {
    scanTargetLabel.textContent = 'CURRENT SECTOR';
    scanBtn.disabled = false;
    return;
  }
  if (scanScale === 'long_range') {
    scanTargetLabel.textContent = 'ALL ADJACENT SECTORS';
    scanBtn.disabled = false;
    return;
  }

  // Targeted scan — check real contacts first; then signal pseudo-contact.
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

  // Recalibration animation during mode switch.
  if (modeSwitchTarget !== null) {
    const progress = Math.min(1, (now - modeSwitchStart) / MODE_SWITCH_MS);
    drawRecalibrationOverlay(progress);
    if (progress >= 1) {
      // Switch complete — snap to new mode.
      scanMode         = modeSwitchTarget;
      modeSwitchTarget = null;
      if (sensorRenderer) {
        sensorRenderer._range = sensorRange * SCAN_MODES[scanMode].rangeScale;
        sensorRenderer.updateContacts(filterContactsForMode(contacts));
      }
      updateModeSelectorUI();
    }
    requestAnimationFrame(renderLoop);
    return;
  }

  sensorRenderer.render(now);

  // Science-specific overlays drawn on top.
  const ctx = sensorCanvas.getContext('2d');
  if (bearingLines.length > 0) {
    drawBearingLines(ctx, sensorCanvas.width, sensorCanvas.height);
  }
  drawModeOverlay(ctx, sensorCanvas.width, sensorCanvas.height);
  if (sectorScanActive) {
    drawSectorSweepOverlay(ctx, sensorCanvas.width, sensorCanvas.height);
  }

  requestAnimationFrame(renderLoop);
}

// ---------------------------------------------------------------------------
// Contact drawing (station-specific, NOT in renderer.js)
// ---------------------------------------------------------------------------

function drawUnknownContact(ctx, sx, sy, selected, modeColor = C_UNKNOWN) {
  ctx.save();
  ctx.translate(sx, sy);

  // Filled dot.
  ctx.fillStyle = selected ? C_SELECTED : modeColor;
  ctx.beginPath();
  ctx.arc(0, 0, 4, 0, Math.PI * 2);
  ctx.fill();

  // Outer ping ring.
  ctx.strokeStyle = selected
    ? 'rgba(0, 170, 255, 0.5)'
    : modeColor + '4d';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(0, 0, selected ? 12 : 9, 0, Math.PI * 2);
  ctx.stroke();

  ctx.restore();
}

function drawScannedContact(ctx, sx, sy, type, selected, modeColor = C_SCANNED) {
  const halfSize = CONTACT_SHAPES[type] ?? CONTACT_SHAPES.cruiser;

  ctx.save();
  ctx.translate(sx, sy);
  ctx.strokeStyle = selected ? C_SELECTED : modeColor;
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
// Scan mode helpers
// ---------------------------------------------------------------------------

/**
 * Filter the raw contacts list to only those detectable in the current mode.
 * EM:   all contacts.
 * GRAV: heavy-mass ships only (cruiser + destroyer — scouts too small).
 * BIO:  bio-signatures require an initial EM lock → only scanned contacts.
 * SUB:  wide-aperture detection — all contacts (same as EM, different rendering).
 */
function filterContactsForMode(raw) {
  switch (scanMode) {
    case 'grav': return raw.filter(c => c.type === 'cruiser' || c.type === 'destroyer');
    case 'bio':  return raw.filter(c => c.scan_state === 'scanned');
    default:     return raw;  // em, sub
  }
}

/**
 * Initiate a 3-second recalibration to the given scan mode.
 * Ignored if already in that mode and not switching.
 */
function requestModeSwitch(mode) {
  if (!gameActive) return;
  if (mode === scanMode && !modeSwitchTarget) return;
  if (modeSwitchTarget === mode) return;
  modeSwitchTarget = mode;
  modeSwitchStart  = performance.now();
  // Update button appearance: dim all, pulse the target.
  for (const btn of Object.values(modeBtnEls)) {
    if (btn) btn.classList.remove('mode-btn--active', 'mode-btn--switching');
  }
  if (modeBtnEls[mode]) modeBtnEls[mode].classList.add('mode-btn--switching');
}

/** Update mode selector button appearance to reflect the active scanMode. */
function updateModeSelectorUI() {
  for (const [m, btn] of Object.entries(modeBtnEls)) {
    if (!btn) continue;
    btn.classList.remove('mode-btn--active', 'mode-btn--switching');
    if (m === scanMode) btn.classList.add('mode-btn--active');
  }
  updateRangeLabel();
  renderContactList();
  updateScanUI();
}

/** Update the RANGE label, accounting for current mode's range scale. */
function updateRangeLabel() {
  const scale = SCAN_MODES[scanMode].rangeScale;
  const r     = sensorRange * scale;
  sensorRangeLabel.textContent = `RANGE: ${(r / 1000).toFixed(0)}km`;
}

/** Wire click handlers for the 4 mode selector buttons. */
function setupModeButtons() {
  for (const [mode, btn] of Object.entries(modeBtnEls)) {
    if (btn) btn.addEventListener('click', () => requestModeSwitch(mode));
  }
}

/** Wire click handlers for the 3 scan scale buttons. */
function setupScaleButtons() {
  const scaleMap = { targeted: 'targeted', sector: 'sector', longrange: 'long_range' };
  for (const [btnKey, scaleKey] of Object.entries(scaleMap)) {
    const btn = scaleBtns[btnKey];
    if (!btn) continue;
    btn.addEventListener('click', () => {
      if (!gameActive || sectorScanActive) return;
      scanScale = scaleKey;
      updateScaleSelectorUI();
    });
  }
}

/** Refresh scale selector button appearance. Locks buttons during active sector scan. */
function updateScaleSelectorUI() {
  const locked = sectorScanActive;
  for (const [btnKey, btn] of Object.entries(scaleBtns)) {
    if (!btn) continue;
    const scaleKey = btnKey === 'longrange' ? 'long_range' : btnKey;
    btn.classList.toggle('scale-btn--active', scaleKey === scanScale && !locked);
    btn.disabled = locked;
  }
  // Lock mode buttons during sector scan too.
  for (const btn of Object.values(modeBtnEls)) {
    if (btn) btn.disabled = locked;
  }
  updateScanUI();
}

/**
 * Draw the recalibration animation that plays during a mode switch.
 * progress ∈ [0, 1] — how far through the 3-second delay we are.
 */
function drawRecalibrationOverlay(progress) {
  const ctx = sensorCanvas.getContext('2d');
  const cw  = sensorCanvas.width;
  const ch  = sensorCanvas.height;
  const mode = SCAN_MODES[modeSwitchTarget];
  const col  = mode.color;

  ctx.clearRect(0, 0, cw, ch);
  ctx.fillStyle = '#050505';
  ctx.fillRect(0, 0, cw, ch);

  // Animated scan sweep.
  const sweepY = progress * ch;
  const grad   = ctx.createLinearGradient(0, Math.max(0, sweepY - 60), 0, sweepY);
  grad.addColorStop(0, 'transparent');
  grad.addColorStop(1, col + '28');
  ctx.fillStyle = grad;
  ctx.fillRect(0, Math.max(0, sweepY - 60), cw, 60);

  ctx.strokeStyle = col + 'aa';
  ctx.lineWidth   = 1;
  ctx.beginPath();
  ctx.moveTo(0, sweepY);
  ctx.lineTo(cw, sweepY);
  ctx.stroke();

  // Progress bar at canvas bottom.
  ctx.fillStyle = col + '55';
  ctx.fillRect(0, ch - 3, cw * progress, 3);

  // Status text.
  ctx.fillStyle    = col;
  ctx.font         = '11px "Share Tech Mono", monospace';
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(`RECALIBRATING — ${mode.fullName}`, cw / 2, ch / 2 - 13);

  ctx.fillStyle = col + '88';
  ctx.font      = '9px "Share Tech Mono", monospace';
  ctx.fillText(`${Math.round(progress * 100)}%`, cw / 2, ch / 2 + 10);
}

/**
 * Radar sweep animation drawn during sector-scale scans.
 * A wedge expands from North clockwise as progress 0→100%.
 * Phase boundaries are marked with faint arcs.
 */
function drawSectorSweepOverlay(ctx, cw, ch) {
  const cx = cw / 2;
  const cy = ch / 2;
  const maxR = Math.hypot(cx, cy);
  const progress = Math.min(100, sectorScanProgress) / 100;
  const sweepAngle = progress * Math.PI * 2;
  const modeColor = SCAN_MODES[scanMode].color;

  // Filled wedge — scanned arc.
  ctx.save();
  ctx.globalAlpha = 0.07;
  ctx.fillStyle   = modeColor;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  // North-up: start angle at -π/2, sweep clockwise.
  ctx.arc(cx, cy, maxR, -Math.PI / 2, -Math.PI / 2 + sweepAngle);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  // Leading sweep line.
  if (progress > 0 && progress < 1) {
    const lineAngle = -Math.PI / 2 + sweepAngle;
    const grad = ctx.createLinearGradient(cx, cy,
      cx + Math.cos(lineAngle) * maxR,
      cy + Math.sin(lineAngle) * maxR);
    grad.addColorStop(0, modeColor + '00');
    grad.addColorStop(1, modeColor + 'cc');
    ctx.save();
    ctx.strokeStyle = grad;
    ctx.lineWidth   = 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(lineAngle) * maxR, cy + Math.sin(lineAngle) * maxR);
    ctx.stroke();
    ctx.restore();
  }

  // Phase boundary arcs at 25 / 50 / 75%.
  const PHASES = [0.25, 0.5, 0.75];
  for (const phaseFrac of PHASES) {
    if (progress <= phaseFrac) break;
    const pAngle = -Math.PI / 2 + phaseFrac * Math.PI * 2;
    ctx.save();
    ctx.strokeStyle = modeColor + '44';
    ctx.lineWidth   = 1;
    ctx.setLineDash([3, 5]);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(pAngle) * maxR, cy + Math.sin(pAngle) * maxR);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }

  // Progress bar at canvas bottom.
  ctx.fillStyle = modeColor + '55';
  ctx.fillRect(0, ch - 3, cw * progress, 3);

  // Status text.
  const scaleText = scanScale === 'sector' ? 'SECTOR SWEEP' : 'LONG-RANGE SCAN';
  const phaseText = `PHASE ${sectorScanPhase + 1}/4`;
  ctx.save();
  ctx.font         = '9px "Share Tech Mono", monospace';
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'top';
  ctx.fillStyle    = modeColor + 'cc';
  ctx.fillText(`${scaleText} — ${phaseText} — ${Math.round(sectorScanProgress)}%`, cw / 2, 24);
  ctx.restore();
}

/**
 * Draw a small mode indicator in the top-left corner of the sensor canvas.
 * Called every frame on top of the normal MapRenderer output.
 */
function drawModeOverlay(ctx, cw, _ch) {
  const mode = SCAN_MODES[scanMode];
  ctx.save();
  ctx.font         = '9px "Share Tech Mono", monospace';
  ctx.textAlign    = 'left';
  ctx.textBaseline = 'top';
  ctx.fillStyle    = mode.color + '88';
  ctx.fillText(`${mode.label} BAND`, 8, 8);
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
