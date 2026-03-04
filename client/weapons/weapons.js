/**
 * Starbridge — Weapons Station
 *
 * Tactical radar display, target selection, beam/torpedo fire controls,
 * and shield balance slider.
 *
 * Server messages received:
 *   ship.state          — position/heading/shields/torpedo ammo/tube cooldowns
 *   sensor.contacts     — range-filtered enemy contacts (replaces world.entities)
 *   ship.hull_hit       — incoming damage flash
 *   ship.system_damaged — system hit notification
 *   weapons.beam_fired  — beam flash animation on radar
 *   weapons.torpedo_hit — torpedo impact flash
 *   game.over           — show defeat overlay
 *
 * Server messages sent:
 *   lobby.claim_role       { role: 'weapons', player_name }
 *   weapons.select_target  { entity_id }
 *   weapons.fire_beams     {}
 *   weapons.fire_torpedo   { tube }
 *   weapons.set_shield_focus { x, y }
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import { setStatusDot, setAlertLevel, showBriefing, showGameOver } from '../shared/ui_components.js';
import { C_PRIMARY, C_PRIMARY_DIM, C_FRIENDLY } from '../shared/renderer.js';
import { MapRenderer } from '../shared/map_renderer.js';
import { RangeControl, STATION_RANGES } from '../shared/range_control.js';
import { initPuzzleRenderer } from '../shared/puzzle_renderer.js';
import { SoundBank } from '../shared/audio.js';
import '../shared/audio_events.js';
import { wireButtonSounds } from '../shared/audio_ui.js';
import { registerHelp, initHelpOverlay } from '../shared/help_overlay.js';
import { initNotifications } from '../shared/notifications.js';
import { initRoleBar } from '../shared/role_bar.js';
import { initCrewRoster } from '../shared/crew_roster.js';

registerHelp([
  { selector: '#radar-canvas',          text: 'Tactical radar — click enemy to select as target.', position: 'right' },
  { selector: '#beam-fire-btn',         text: 'Fire beams — hold for sustained fire within weapon arc.', position: 'left' },
  { selector: '#tube1-fire-btn',        text: 'Fire torpedo tube 1 — needs ammo loaded.', position: 'left' },
  { selector: '#tube2-fire-btn',        text: 'Fire torpedo tube 2 — independent reload timer.', position: 'left' },
  { selector: '#shield-focus-canvas',   text: 'Shield focus — drag to direct shield energy across all four facings.', position: 'above' },
]);

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const RADAR_WORLD_RADIUS  = 50_000;  // world units shown at radar edge
const BEAM_FLASH_MS       = 300;     // beam fire line animation duration
const HIT_FLASH_MS        = 500;     // hull-hit border flash duration
const TUBE_LOAD_TIME      = 3.0;     // must match server TUBE_LOAD_TIME
const TORPEDO_TYPES       = ['standard', 'homing', 'ion', 'piercing', 'heavy', 'proximity', 'nuclear', 'experimental'];
const TYPE_ABBREV         = { standard: 'STD', homing: 'HOM', ion: 'ION', piercing: 'PRC',
                               heavy: 'HVY', proximity: 'PRX', nuclear: 'NUC', experimental: 'EXP' };
const TYPE_COLORS         = { standard: '#00ff41', homing: '#00ffcc', ion:  '#00c8ff',
                               piercing: '#44aaff', heavy:  '#ff8800', proximity: '#ffcc00',
                               nuclear:  '#ff4040', experimental: '#cc44ff' };
// Per-type reload times (must mirror TORPEDO_RELOAD_BY_TYPE on server).
const TYPE_RELOAD_TIMES   = { standard: 3.0, homing: 4.0, ion: 5.0, piercing: 4.0,
                               heavy: 8.0, proximity: 4.0, nuclear: 10.0, experimental: 6.0 };
const TYPE_DESCRIPTIONS   = {
  standard:     '50 DMG | 500 m/s | 3s reload\nBalanced general-purpose torpedo',
  homing:       '35 DMG | 500 m/s | 4s reload\nTracks target — effective vs fast ships',
  ion:          '10 DMG | 500 m/s | 5s reload\nDrains shields + stuns systems 10s',
  piercing:     '40 DMG | 400 m/s | 4s reload\nIgnores 75% of shield absorption',
  heavy:        '100 DMG | 300 m/s | 8s reload\nMaximum impact — slow, easily intercepted',
  proximity:    '30 DMG | 500 m/s | 4s reload\nAOE blast — hits all enemies in radius',
  nuclear:      '200 DMG | 400 m/s | 10s reload\nDevastating — requires Captain authorisation',
  experimental: '60 DMG | 500 m/s | 6s reload\nUnpredictable secondary effects',
};
// Per-type torpedo speed (must mirror TORPEDO_VELOCITY_BY_TYPE on server).
const TYPE_VELOCITY       = { standard: 500, homing: 500, ion: 500, piercing: 400,
                               heavy: 300, proximity: 500, nuclear: 400, experimental: 500 };
const TRAIL_LENGTH        = 5;       // torpedo trail positions to store
const EXPLOSION_DURATION  = 500;     // explosion ring animation duration ms

// Enemy wireframe sizes (half-size in pixels at radar scale)
const ENEMY_SHAPES = {
  scout:     { size: 8  },
  cruiser:   { size: 10 },
  destroyer: { size: 13 },
};

// Contact colours by classification.
const CONTACT_COLORS = {
  hostile:  '#ff4040',   // confirmed enemy — red
  unknown:  '#ffffff',   // unscanned — white (pulsing)
  friendly: '#00ff41',   // friendly transponder — green
  neutral:  '#ffaa00',   // neutral / derelict — amber
};

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusDotEl    = document.querySelector('[data-status-dot]');
const statusLabelEl  = document.querySelector('[data-status-label]');
const standbyEl      = document.querySelector('[data-standby]');
const weaponsMainEl  = document.querySelector('[data-weapons-main]');
const missionLabelEl = document.getElementById('mission-label');
const stationEl      = document.getElementById('station-container');

// Radar
const radarCanvas = document.getElementById('radar-canvas');

// Target info
const targetIdLabel          = document.getElementById('target-id-label');
const targetClassificationEl = document.getElementById('target-classification');
const targetHullFill         = document.getElementById('target-hull-fill');
const targetHullText         = document.getElementById('target-hull-text');
const targetShieldFwdFill    = document.getElementById('target-shield-fwd-fill');
const targetShieldFwdText    = document.getElementById('target-shield-fwd-text');
const targetShieldAftFill    = document.getElementById('target-shield-aft-fill');
const targetShieldAftText    = document.getElementById('target-shield-aft-text');
const targetRange            = document.getElementById('target-range');
const targetBearing          = document.getElementById('target-bearing');
const targetTypeEl           = document.getElementById('target-type');
const targetAdvisoryEl       = document.getElementById('target-advisory');

// Beam
const beamFireBtn  = document.getElementById('beam-fire-btn');
const beamStatus   = document.getElementById('beam-status');

// Torpedoes
const ammoLabel      = document.getElementById('torpedo-ammo-label');
const tube1ReloadFill = document.getElementById('tube1-reload-fill');
const tube2ReloadFill = document.getElementById('tube2-reload-fill');
const tube1Status    = document.getElementById('tube1-status');
const tube2Status    = document.getElementById('tube2-status');
const tube1FireBtn   = document.getElementById('tube1-fire-btn');
const tube2FireBtn   = document.getElementById('tube2-fire-btn');

// Shield focus
const shieldCanvas    = document.getElementById('shield-focus-canvas');
const shldForePct     = document.getElementById('shld-fore-pct');
const shldAftPct      = document.getElementById('shld-aft-pct');
const shldPortPct     = document.getElementById('shld-port-pct');
const shldStarPct     = document.getElementById('shld-star-pct');
const shieldLockXBtn  = document.getElementById('shield-lock-x');
const shieldLockYBtn  = document.getElementById('shield-lock-y');
const shieldCentreBtn = document.getElementById('shield-centre');

const rangeBarEl = document.getElementById('range-bar');

// ---------------------------------------------------------------------------
// Game state
// ---------------------------------------------------------------------------

let gameActive    = false;
let radarCtx      = null;
let radarRenderer = null;  // MapRenderer instance
let rangeControl  = null;
let hintsEnabled  = false;  // true when difficulty === 'cadet'

let shipState   = null;   // most recent ship.state payload
let contacts    = [];     // world.entities enemies array
let torpedoes   = [];     // world.entities torpedoes array
let selectedId  = null;   // selected enemy entity_id or null
let suggestedId = null;   // cadet hint: nearest/lowest-hull contact
let _lastTargetData = null;  // last known target snapshot (for lost contact)

// Tube state (from ship.state).
let tubeTypes       = ['standard', 'standard'];
let tubeLoading     = [0.0, 0.0];
let tubeReloadTimes = [3.0, 3.0];  // reference reload time per tube (set when fired)

// Per-type ammo (from ship.state.torpedo_ammo dict).
let torpedoAmmo    = {};   // type → current count
let torpedoAmmoMax = {};   // type → max count

// Pending nuclear auth: request_id for each tube (or null).
let pendingAuth = [null, null];

// Shield focus state.
let _sfSilhouetteImg = null;        // ship silhouette for shield focus canvas
let _sfX = 0.0, _sfY = 0.0;        // focus point (-1..+1)
let _sfLockX = false, _sfLockY = false;
let _sfDragging = false;
let _sfSendTimer = null;

// Beam frequency selection.
let currentFrequency = 'alpha';

// Beam flash: { targetX, targetY, startTime }
let beamFlash   = null;

// Hull-hit flash timestamp
let hitFlashTime = -Infinity;

// Explosion rings: [{x, y, startTime}]
const explosions = [];

// Torpedo track lines: record first-seen position per torpedo id.
const _torpedoLaunchPos = new Map();

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();

    // Re-claim role so this connection receives role-filtered sensor.contacts.
    if (status === 'connected') {
      const name = sessionStorage.getItem('player_name') || 'WEAPONS';
      send('lobby.claim_role', { role: 'weapons', player_name: name });
    }
  });

  on('game.started',                 handleGameStarted);
  on('ship.state',                   handleShipState);
  on('ship.alert_changed',           ({ level }) => setAlertLevel(level));
  on('sensor.contacts',              handleSensorContacts);
  on('ship.hull_hit',                handleHullHit);
  on('ship.system_damaged',          handleSystemDamaged);
  on('weapons.beam_fired',           handleBeamFired);
  on('weapons.torpedo_hit',          handleTorpedoHit);
  on('weapons.tube_loading',         handleTubeLoading);
  on('weapons.tube_loaded',          handleTubeLoaded);
  on('captain.authorization_request',  handleAuthRequest);
  on('weapons.authorization_result',   handleAuthResult);
  on('weapons.targeting_denied',       handleTargetingDenied);
  on('weapons.diplomatic_incident',    handleDiplomaticIncident);
  on('game.over',                      handleGameOver);
  on('comms.contacts',                 handleCommsContacts);
  on('flag_bridge.priority',           handleFlagBridgePriority);
  on('spinal.state',                   handleSpinalState);

  initPuzzleRenderer(send);
  setupControls();
  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();
  initNotifications(send, 'weapons');
  initRoleBar(send, 'weapons');
  initCrewRoster(send);
  on('weapons.torpedo_fired', () => SoundBank.play('torpedo_launch'));
  connect();
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function handleGameStarted(payload) {
  missionLabelEl.textContent = payload.mission_name.toUpperCase();
  standbyEl.style.display    = 'none';
  weaponsMainEl.style.display = 'grid';
  hintsEnabled = payload.difficulty === 'cadet';
  gameActive = true;

  // Ship-class-specific panels
  const sc = payload.ship_class || '';
  const spinalPanel = document.getElementById('spinal-mount-panel');
  const dualPanel   = document.getElementById('dual-target-panel');
  if (spinalPanel) spinalPanel.style.display = sc === 'battleship' ? '' : 'none';
  if (dualPanel)   dualPanel.style.display   = (sc === 'cruiser' || sc === 'battleship') ? '' : 'none';

  // Load ship silhouette for shield focus canvas.
  if (sc) {
    const img = new Image();
    img.src = `/client/shared/silhouettes/${sc}.svg`;
    img.onload = () => { _sfSilhouetteImg = img; };
  }

  // Range control (replaces old fixed RADAR_WORLD_RADIUS).
  const wpnRanges = STATION_RANGES.weapons;
  rangeControl = new RangeControl({
    container:    rangeBarEl,
    stationId:    'weapons',
    ranges:       wpnRanges.available,
    defaultRange: wpnRanges.default,
    onChange:      _onRangeChange,
  });
  rangeControl.attach();

  requestAnimationFrame(() => {
    radarCtx = radarCanvas.getContext('2d');
    resizeRadar();
    window.addEventListener('resize', resizeRadar);

    // Create MapRenderer for radar (contacts + grid; beam arc drawn separately).
    radarRenderer = new MapRenderer(radarCanvas, {
      range: rangeControl.currentRangeUnits(),
      orientation: 'north-up',
      showGrid: false,
      showRangeRings: true,
      interactive: true,
      zoom: { enabled: true },
      drawContact: (ctx, sx, sy, contact, selected, now) => {
        const cls  = contact.classification || 'hostile';
        const kind = contact.kind || 'enemy';

        // Determine colour; unknown contacts pulse white.
        let color;
        if (cls === 'unknown') {
          const alpha = 0.5 + 0.2 * Math.sin(now * 0.004);
          color = `rgba(255,255,255,${alpha})`;
        } else {
          color = CONTACT_COLORS[cls] || CONTACT_COLORS.hostile;
        }

        // Cadet hint ring (hostile/unknown only — never suggest friendly).
        if (hintsEnabled && contact.id === suggestedId && !selected && cls !== 'friendly') {
          const pulse = 0.5 + 0.5 * Math.sin(now * 0.004);
          const hintR = (ENEMY_SHAPES[contact.type]?.size || 10) + 10;
          ctx.save();
          ctx.strokeStyle  = `rgba(255, 176, 0, ${0.5 + 0.4 * pulse})`;
          ctx.lineWidth    = 1.5;
          ctx.setLineDash([4, 4]);
          ctx.beginPath();
          ctx.arc(sx, sy, hintR, 0, Math.PI * 2);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle    = `rgba(255, 176, 0, ${0.6 + 0.3 * pulse})`;
          ctx.font         = '10px "Share Tech Mono", monospace';
          ctx.textAlign    = 'center';
          ctx.textBaseline = 'bottom';
          ctx.fillText('SUGGESTED TARGET', sx, sy - hintR - 4);
          ctx.restore();
        }

        if (kind === 'station') {
          drawStationShape(ctx, sx, sy, color, selected);
        } else if (kind === 'creature') {
          drawCreatureShape(ctx, sx, sy, color, selected);
          const ctype = (contact.creature_type || '').replace(/_/g, ' ').toUpperCase();
          ctx.fillStyle = '#ff44ff';
          ctx.font = '11px "Share Tech Mono", monospace';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          ctx.fillText(ctype ? `CREATURE: ${ctype}` : contact.id, sx, sy + 14);
        } else if (kind === 'wreck') {
          // Pulsing cyan diamond with "?".
          const pulse = 0.6 + 0.4 * Math.sin(now * 0.004);
          const ws = 8;
          ctx.save();
          ctx.translate(sx, sy);
          ctx.strokeStyle = '#00ddff';
          ctx.lineWidth = selected ? 2.5 : 1.5;
          ctx.globalAlpha = pulse;
          ctx.beginPath();
          ctx.moveTo(0, -ws); ctx.lineTo(ws, 0);
          ctx.lineTo(0, ws);  ctx.lineTo(-ws, 0);
          ctx.closePath();
          ctx.stroke();
          ctx.fillStyle = '#00ddff';
          ctx.font = 'bold 11px monospace';
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('?', 0, 0);
          if (selected) {
            ctx.strokeStyle = C_FRIENDLY;
            ctx.lineWidth = 1;
            ctx.globalAlpha = 1;
            ctx.beginPath();
            ctx.arc(0, 0, ws + 6, 0, Math.PI * 2);
            ctx.stroke();
          }
          ctx.restore();
          const wtype = (contact.enemy_type || '').replace(/_/g, ' ').toUpperCase();
          ctx.fillStyle = '#00ddff';
          ctx.globalAlpha = 0.8;
          ctx.font = '11px "Share Tech Mono", monospace';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          ctx.fillText(wtype ? `WRECK: ${wtype}` : contact.id, sx, sy + ws + 3);
          ctx.globalAlpha = 1;
        } else {
          drawEnemyShape(ctx, sx, sy, contact.type,
            (ENEMY_SHAPES[contact.type] || ENEMY_SHAPES.cruiser).size,
            color, selected);
          if (!contact.type) {
            ctx.fillStyle = color;
            ctx.font = '11px "Share Tech Mono", monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            ctx.fillText('CONTACT', sx, sy + 12);
          }
        }
      },
    });
    radarRenderer.loadShipSilhouette(sc);
    radarRenderer.onContactClick((id) => selectTarget(id));
    _updateWeaponRangeRings();

    requestAnimationFrame(renderLoop);
  });

  if (payload.briefing_text) {
    showBriefing(payload.mission_name, payload.briefing_text);
  }

  // Initialise shield focus canvas.
  _drawShieldFocus(_calcShieldDist(0, 0));

  console.log(`[weapons] Game started — mission: ${payload.mission_id}`);
}

function handleShipState(payload) {
  if (!gameActive) return;
  shipState = payload;
  if (radarRenderer) radarRenderer.updateShipState(payload);
  if (payload.tube_types)        tubeTypes       = payload.tube_types;
  if (payload.tube_loading)      tubeLoading     = payload.tube_loading;
  if (payload.tube_reload_times) tubeReloadTimes = payload.tube_reload_times;
  if (payload.torpedo_ammo && typeof payload.torpedo_ammo === 'object')
    torpedoAmmo = payload.torpedo_ammo;
  if (payload.torpedo_ammo_max && typeof payload.torpedo_ammo_max === 'object')
    torpedoAmmoMax = payload.torpedo_ammo_max;
  updateTubeUI(payload);
  updateMagazinePanel();
  _updateLoadButtons();
  _updateWeaponRangeRings();

  // Shield focus update (from server state).
  if (payload.shield_distribution) {
    const d = payload.shield_distribution;
    _updateShieldPctLabels(d);
    if (!_sfDragging) {
      if (payload.shield_focus) { _sfX = payload.shield_focus.x; _sfY = payload.shield_focus.y; }
      _drawShieldFocus(d);
    }
  }
}

function handleSensorContacts(payload) {
  if (!gameActive) return;
  contacts  = payload.contacts  || [];
  torpedoes = payload.torpedoes || [];

  // Cadet hint: nearest hostile/unknown contact (never friendly).
  if (hintsEnabled && contacts.length > 0 && shipState) {
    let nearest = null, minDist = Infinity;
    for (const c of contacts) {
      if (c.classification === 'friendly') continue;
      const dx = c.x - shipState.position.x;
      const dy = c.y - shipState.position.y;
      const d  = Math.hypot(dx, dy);
      if (d < minDist) { minDist = d; nearest = c; }
    }
    suggestedId = nearest ? nearest.id : null;
  } else {
    suggestedId = null;
  }

  // Record launch position for new torpedoes; clean up dead ones.
  for (const t of torpedoes) {
    if (!_torpedoLaunchPos.has(t.id)) _torpedoLaunchPos.set(t.id, { x: t.x, y: t.y });
  }
  const _liveIds = new Set(torpedoes.map(t => t.id));
  for (const id of _torpedoLaunchPos.keys()) {
    if (!_liveIds.has(id)) _torpedoLaunchPos.delete(id);
  }

  if (radarRenderer) radarRenderer.updateContacts(contacts, torpedoes);
  updateTargetPanel();
}

function handleCommsContacts(payload) {
  if (!gameActive) return;
  if (radarRenderer) radarRenderer.updateCommsContacts(payload.contacts || []);
}

// ---------------------------------------------------------------------------
// Flag Bridge priority (cruiser) + Spinal Mount (battleship)
// ---------------------------------------------------------------------------

let _flagPriorityQueue = [];
let _spinalState = null;

function handleFlagBridgePriority(payload) {
  _flagPriorityQueue = payload.priority_queue || [];
  const el = document.getElementById('flag-priority-panel');
  if (!el) return;
  if (!_flagPriorityQueue.length && !payload.weapons_override) { el.style.display = 'none'; return; }
  el.style.display = '';
  const override = payload.weapons_override ? ' (OVERRIDE)' : '';
  el.innerHTML =
    `<div class="panel-header">FLAG BRIDGE PRIORITY${override}</div>` +
    `<div class="panel-body">${_flagPriorityQueue.length} target(s) queued</div>`;
}

function handleSpinalState(payload) {
  _spinalState = payload;
  const el = document.getElementById('spinal-mount-panel');
  if (!el) return;
  if (!payload.active) { el.style.display = 'none'; return; }
  el.style.display = '';
  const charge = payload.charge_progress || 0;
  const state = (payload.state || 'idle').toUpperCase();
  const cd = payload.cooldown_remaining > 0 ? ` CD:${Math.round(payload.cooldown_remaining)}s` : '';
  const align = typeof payload.alignment === 'number' ? `${Math.round(payload.alignment)}%` : 'N/A';
  const content = document.getElementById('spinal-mount-content');
  if (content) {
    content.innerHTML =
      `<div>${state} ${charge}%${cd}</div>` +
      `<div>Alignment: ${align}</div>` +
      `<div>Power draw: ${payload.power_draw || 0}</div>`;
  }
}

function handleHullHit() {
  if (!gameActive) return;
  SoundBank.play('hull_hit');
  hitFlashTime = performance.now();
  stationEl.classList.add('hit');
  setTimeout(() => stationEl.classList.remove('hit'), HIT_FLASH_MS);
  if (radarRenderer && shipState?.position) {
    radarRenderer.addDamageEvent(shipState.position.x, shipState.position.y);
  }
}

function handleSystemDamaged(payload) {
  if (!gameActive) return;
  SoundBank.play('system_damage');
  console.log(`[weapons] System damaged: ${payload.system} → ${payload.new_health.toFixed(1)} HP`);
}

function handleBeamFired(payload) {
  if (!gameActive) return;
  SoundBank.play('beam_fire');
  beamFlash = {
    targetX:   payload.target_x,
    targetY:   payload.target_y,
    startTime: performance.now(),
  };
  // Also tell MapRenderer (for its beam flash line).
  if (radarRenderer) radarRenderer.setBeamFlash(payload.target_x, payload.target_y);
}

function handleTorpedoHit(payload) {
  if (!gameActive) return;
  SoundBank.play('torpedo_impact');
  // Spawn explosion at last known position of the torpedo.
  if (radarRenderer) {
    const last = radarRenderer.getLastTorpedoPosition(payload.torpedo_id);
    if (last) explosions.push({ x: last.x, y: last.y, startTime: performance.now() });
  }
  torpedoes = torpedoes.filter(t => t.id !== payload.torpedo_id);
}

function handleGameOver(payload) {
  gameActive = false;
  SoundBank.play(payload.result === 'victory' ? 'victory' : 'defeat');
  showGameOver(payload.result, payload.stats || {});
}

function handleTubeLoading({ tube, torpedo_type, load_time }) {
  if (!gameActive) return;
  const idx = tube - 1;
  tubeLoading[idx] = load_time;
  console.log(`[weapons] Tube ${tube} loading: ${torpedo_type}`);
}

function handleTubeLoaded({ tube, torpedo_type }) {
  if (!gameActive) return;
  const idx = tube - 1;
  tubeLoading[idx] = 0.0;
  tubeTypes[idx]   = torpedo_type;
  console.log(`[weapons] Tube ${tube} loaded: ${torpedo_type}`);
}

function handleAuthRequest({ request_id, action, tube }) {
  if (!gameActive) return;
  const idx = tube - 1;
  pendingAuth[idx] = request_id;
  _setTubeAuthStatus(tube, true);
  console.log(`[weapons] Nuclear auth requested: ${request_id} (tube ${tube})`);
}

function handleAuthResult({ request_id, approved, tube }) {
  if (!gameActive) return;
  const idx = tube - 1;
  if (pendingAuth[idx] === request_id) {
    pendingAuth[idx] = null;
    _setTubeAuthStatus(tube, false);
  }
  console.log(`[weapons] Nuclear auth ${approved ? 'APPROVED' : 'DENIED'} (tube ${tube})`);
}

function _setTubeAuthStatus(tube, pending) {
  const statusEl = document.getElementById(`tube${tube}-status`);
  const fireBtn  = document.getElementById(`tube${tube}-fire-btn`);
  if (statusEl) statusEl.textContent = pending ? 'AWAITING AUTH' : '';
  if (fireBtn)  fireBtn.disabled = pending;
}

function _showDenial(id) {
  const prev      = beamStatus.textContent;
  const prevColor = beamStatus.style.color;
  beamStatus.textContent   = 'TARGETING DENIED — FRIENDLY CONTACT';
  beamStatus.style.color   = CONTACT_COLORS.friendly;
  setTimeout(() => {
    beamStatus.textContent = prev;
    beamStatus.style.color = prevColor;
  }, 2500);
  console.warn(`[weapons] Targeting denied: friendly contact ${id}`);
}

function handleTargetingDenied({ entity_id }) {
  _showDenial(entity_id || '?');
}

function handleDiplomaticIncident({ station_id, station_name }) {
  const name      = (station_name || station_id || 'UNKNOWN').toUpperCase();
  const prev      = beamStatus.textContent;
  const prevColor = beamStatus.style.color;
  beamStatus.textContent   = `DIPLOMATIC INCIDENT — ${name} NOW HOSTILE`;
  beamStatus.style.color   = CONTACT_COLORS.neutral;
  setTimeout(() => {
    beamStatus.textContent = prev;
    beamStatus.style.color = prevColor;
  }, 4000);
  console.warn(`[weapons] Diplomatic incident — ${station_name} (${station_id}) is now hostile`);
}

// ---------------------------------------------------------------------------
// Control setup
// ---------------------------------------------------------------------------

function setupControls() {
  // Beam — hold to auto-repeat at ~2 Hz.
  let beamInterval = null;

  function startFiringBeams() {
    if (!gameActive) return;
    send('weapons.fire_beams', { beam_frequency: currentFrequency });
    beamInterval = setInterval(() => {
      if (!gameActive) { stopFiringBeams(); return; }
      send('weapons.fire_beams', { beam_frequency: currentFrequency });
    }, 500);
  }

  function stopFiringBeams() {
    if (beamInterval !== null) {
      clearInterval(beamInterval);
      beamInterval = null;
    }
  }

  beamFireBtn.addEventListener('mousedown', startFiringBeams);
  beamFireBtn.addEventListener('touchstart', (e) => { e.preventDefault(); startFiringBeams(); });
  window.addEventListener('mouseup', stopFiringBeams);
  window.addEventListener('touchend', stopFiringBeams);

  // Torpedo tubes.
  tube1FireBtn.addEventListener('click', () => {
    if (!gameActive) return;
    SoundBank.play('torpedo_launch');
    send('weapons.fire_torpedo', { tube: 1 });
  });

  tube2FireBtn.addEventListener('click', () => {
    if (!gameActive) return;
    SoundBank.play('torpedo_launch');
    send('weapons.fire_torpedo', { tube: 2 });
  });

  // Beam frequency selector buttons.
  document.querySelectorAll('.freq-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      currentFrequency = btn.dataset.freq;
      document.querySelectorAll('.freq-btn').forEach(b => b.classList.remove('freq-btn--active'));
      btn.classList.add('freq-btn--active');
    });
  });

  // Load type buttons — inject into the torpedo section dynamically.
  _buildLoadControls();

  // Shield focus — drag on canvas.
  if (shieldCanvas) {
    shieldCanvas.addEventListener('mousedown', e => { _sfDragging = true; _sfHandleDrag(e); });
    shieldCanvas.addEventListener('touchstart', e => {
      _sfDragging = true; _sfHandleDrag(e.touches[0]); e.preventDefault();
    }, { passive: false });
    shieldCanvas.addEventListener('keydown', e => {
      const NUDGE = 0.05;
      if (e.key === 'ArrowLeft')  { _sfX = Math.max(-1, _sfX - NUDGE); _sfApplyAndSend(); e.preventDefault(); }
      if (e.key === 'ArrowRight') { _sfX = Math.min( 1, _sfX + NUDGE); _sfApplyAndSend(); e.preventDefault(); }
      if (e.key === 'ArrowUp')    { _sfY = Math.min( 1, _sfY + NUDGE); _sfApplyAndSend(); e.preventDefault(); }
      if (e.key === 'ArrowDown')  { _sfY = Math.max(-1, _sfY - NUDGE); _sfApplyAndSend(); e.preventDefault(); }
      if (e.key === 'x' || e.key === 'X') { _sfLockX = !_sfLockX; _sfUpdateLockUI(); }
      if (e.key === 'y' || e.key === 'Y') { _sfLockY = !_sfLockY; _sfUpdateLockUI(); }
      if (e.key === 'c' || e.key === 'C') { _sfX = 0; _sfY = 0; _sfLockX = false; _sfLockY = false; _sfUpdateLockUI(); _sfApplyAndSend(); }
    });
  }
  document.addEventListener('mousemove', e => { if (_sfDragging) _sfHandleDrag(e); });
  document.addEventListener('mouseup',   () => { _sfDragging = false; });
  document.addEventListener('touchmove', e => {
    if (_sfDragging) { _sfHandleDrag(e.touches[0]); e.preventDefault(); }
  }, { passive: false });
  document.addEventListener('touchend', () => { _sfDragging = false; });

  // Shield quick buttons.
  shieldLockXBtn?.addEventListener('click', () => { _sfLockX = !_sfLockX; _sfUpdateLockUI(); });
  shieldLockYBtn?.addEventListener('click', () => { _sfLockY = !_sfLockY; _sfUpdateLockUI(); });
  shieldCentreBtn?.addEventListener('click', () => {
    _sfX = 0; _sfY = 0; _sfLockX = false; _sfLockY = false;
    _sfUpdateLockUI(); _sfApplyAndSend();
  });

  // Radar click is handled by MapRenderer's onContactClick callback.
}

function _buildLoadControls() {
  // Find the torpedo tubes section.
  const torpSection = document.querySelector('.ctrl-section:nth-of-type(3)');
  if (!torpSection) return;

  // Add type badges to tube rows.
  const tubeRows = torpSection.querySelectorAll('.tube-row');
  tubeRows.forEach((row, idx) => {
    const badge = document.createElement('span');
    badge.id        = `tube${idx + 1}-type`;
    badge.className = 'text-label tube-type-badge';
    badge.textContent = 'STD';
    row.insertBefore(badge, row.querySelector('.fire-btn'));
  });

  // Magazine panel (per-type ammo display).
  const magSection = document.createElement('div');
  magSection.id = 'magazine-panel';
  magSection.className = 'magazine-panel';
  torpSection.appendChild(magSection);

  // Load selector for each tube.
  const loadSection = document.createElement('div');
  loadSection.className = 'tube-load-section';
  loadSection.innerHTML = `
    <div class="text-dim text-label" style="margin-bottom:4px">LOAD TYPE</div>
    <div class="tube-load-row" id="tube-load-btns">
      ${TORPEDO_TYPES.map(t => {
        const abbr = TYPE_ABBREV[t] || t.toUpperCase();
        const desc = TYPE_DESCRIPTIONS[t] || '';
        return `
        <button class="load-btn" data-type="${t}" style="border-color:${TYPE_COLORS[t]}"
                title="${abbr} — ${desc}">
          <span class="load-btn-label">${abbr}</span>
          <span class="load-btn-count" id="load-count-${t}">0</span>
        </button>`;
      }).join('')}
      <select class="load-tube-select text-data" id="load-tube-sel">
        <option value="1">T1</option>
        <option value="2">T2</option>
      </select>
    </div>
  `;
  torpSection.appendChild(loadSection);

  // Wire load buttons.
  loadSection.querySelectorAll('.load-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (!gameActive) return;
      const tube = parseInt(document.getElementById('load-tube-sel').value, 10);
      const type = btn.dataset.type;
      send('weapons.load_tube', { tube, torpedo_type: type });
    });
  });
}

function selectTarget(id) {
  const contact = contacts.find(c => c.id === id);
  if (contact && contact.classification === 'friendly') {
    _showDenial(id);
    return;
  }
  selectedId = id;
  if (radarRenderer) radarRenderer.selectContact(id);
  send('weapons.select_target', { entity_id: id });
  updateTargetPanel();
  _updateLoadButtons();
}

// ---------------------------------------------------------------------------
// Shield focus helpers
// ---------------------------------------------------------------------------

function _calcShieldDist(x, y) {
  const base = 0.25, bias = 0.25;
  const fore = base + y * bias;
  const aft  = base - y * bias;
  const star = base + x * bias;
  const port = base - x * bias;
  const t = fore + aft + star + port;
  return { fore: fore / t, aft: aft / t, starboard: star / t, port: port / t };
}

function _drawShieldFocus(dist) {
  if (!shieldCanvas) return;
  const ctx = shieldCanvas.getContext('2d');
  const W = shieldCanvas.width, H = shieldCanvas.height;
  const cx = W / 2, cy = H / 2;

  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#000a14';
  ctx.fillRect(0, 0, W, H);

  // Hull outline (silhouette SVG or fallback rect, 60% of canvas, centred).
  const hullW = W * 0.6, hullH = H * 0.6;
  const hullX = (W - hullW) / 2, hullY = (H - hullH) / 2;
  if (_sfSilhouetteImg) {
    ctx.save();
    ctx.globalAlpha = 0.3;
    ctx.drawImage(_sfSilhouetteImg, hullX, hullY, hullW, hullH);
    ctx.restore();
  } else {
    ctx.strokeStyle = 'rgba(0,170,255,0.3)';
    ctx.lineWidth = 1;
    ctx.strokeRect(hullX, hullY, hullW, hullH);
  }

  // 4 edge bands.
  const bands = [
    { facing: 'fore',      x: 0,       y: 0,       w: W,   h: 0 },
    { facing: 'aft',       x: 0,       y: H,       w: W,   h: 0 },
    { facing: 'port',      x: 0,       y: 0,       w: 0,   h: H },
    { facing: 'starboard', x: W,       y: 0,       w: 0,   h: H },
  ];
  const facingRects = {
    fore:      (t) => ({ x: 0,     y: 0,     w: W,  h: t  }),
    aft:       (t) => ({ x: 0,     y: H - t, w: W,  h: t  }),
    port:      (t) => ({ x: 0,     y: 0,     w: t,  h: H  }),
    starboard: (t) => ({ x: W - t, y: 0,     w: t,  h: H  }),
  };
  for (const facing of ['fore', 'aft', 'port', 'starboard']) {
    const f   = dist[facing] ?? 0.25;
    const t   = Math.round(f * 16);
    const alpha = Math.min(0.9, f * 2);
    ctx.fillStyle = `rgba(0,170,255,${alpha})`;
    const r = facingRects[facing](t);
    ctx.fillRect(r.x, r.y, r.w, r.h);
  }

  // Axis lock lines (dashed).
  if (_sfLockX || _sfLockY) {
    ctx.strokeStyle = 'rgba(255,176,0,0.5)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    if (_sfLockX) {
      ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, H); ctx.stroke();
    }
    if (_sfLockY) {
      ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(W, cy); ctx.stroke();
    }
    ctx.setLineDash([]);
  }

  // Focus dot.
  const fx = cx + _sfX * (cx - 6);
  const fy = cy - _sfY * (cy - 6);
  ctx.beginPath();
  ctx.arc(fx, fy, 5, 0, Math.PI * 2);
  ctx.fillStyle = '#ff4040';
  ctx.fill();
}

function _updateShieldPctLabels(d) {
  if (shldForePct) shldForePct.textContent = `${Math.round(d.fore * 100)}%`;
  if (shldAftPct)  shldAftPct.textContent  = `${Math.round(d.aft  * 100)}%`;
  if (shldPortPct) shldPortPct.textContent = `${Math.round(d.port * 100)}%`;
  if (shldStarPct) shldStarPct.textContent = `${Math.round(d.starboard * 100)}%`;
}

function _sfUpdateLockUI() {
  shieldLockXBtn?.classList.toggle('shield-quick-btn--active', _sfLockX);
  shieldLockYBtn?.classList.toggle('shield-quick-btn--active', _sfLockY);
}

function _sfHandleDrag(e) {
  if (!shieldCanvas) return;
  const r = shieldCanvas.getBoundingClientRect();
  let x = ((e.clientX - r.left)  / r.width)  * 2 - 1;
  let y = -((e.clientY - r.top) / r.height) * 2 + 1;
  x = Math.max(-1, Math.min(1, x));
  y = Math.max(-1, Math.min(1, y));
  if (_sfLockX) x = 0;
  if (_sfLockY) y = 0;
  _sfX = x; _sfY = y;
  const d = _calcShieldDist(x, y);
  _drawShieldFocus(d);
  _updateShieldPctLabels(d);
  _sfThrottleSend();
}

function _sfThrottleSend() {
  if (_sfSendTimer) return;
  _sfSendTimer = setTimeout(() => {
    _sfSendTimer = null;
    if (gameActive) send('weapons.set_shield_focus', { x: _sfX, y: _sfY });
  }, 100);
}

function _sfApplyAndSend() {
  const d = _calcShieldDist(_sfX, _sfY);
  _drawShieldFocus(d);
  _updateShieldPctLabels(d);
  _sfThrottleSend();
}

// ---------------------------------------------------------------------------
// UI updates
// ---------------------------------------------------------------------------

function updateTargetPanel() {
  const target = contacts.find(c => c.id === selectedId);

  const shieldFreqRowEl = document.getElementById('target-shield-freq-row');
  const shieldFreqEl    = document.getElementById('target-shield-freq');

  if (!target && !selectedId) {
    // No target selected at all.
    _lastTargetData = null;
    targetIdLabel.textContent            = 'NONE';
    if (targetClassificationEl) { targetClassificationEl.textContent = ''; targetClassificationEl.style.display = 'none'; }
    if (targetAdvisoryEl)       { targetAdvisoryEl.textContent = ''; targetAdvisoryEl.style.display = 'none'; }
    targetHullFill.style.width           = '0%';
    targetHullText.textContent           = '—';
    targetShieldFwdFill.style.width      = '0%';
    targetShieldFwdText.textContent      = '—';
    targetShieldAftFill.style.width      = '0%';
    targetShieldAftText.textContent      = '—';
    targetRange.textContent              = '—';
    targetBearing.textContent            = '—';
    targetTypeEl.textContent             = '—';
    beamStatus.textContent               = 'NO TARGET';
    beamFireBtn.disabled                 = true;
    if (shieldFreqRowEl) shieldFreqRowEl.style.display = 'none';
    return;
  }

  if (!target && selectedId) {
    // Target was selected but dropped off sensors — show last known data.
    targetIdLabel.textContent = selectedId.toUpperCase();
    if (targetAdvisoryEl) {
      targetAdvisoryEl.textContent   = 'CONTACT LOST — last known data';
      targetAdvisoryEl.style.display = '';
      targetAdvisoryEl.style.color   = 'var(--danger, #ff4040)';
    }
    targetRange.textContent   = 'LOST';
    targetBearing.textContent = '—';
    beamStatus.textContent    = 'CONTACT LOST';
    beamFireBtn.disabled      = true;
    // Keep last known hull/shield/type data visible (already rendered).
    return;
  }

  // Cache current data for lost-contact fallback.
  _lastTargetData = { id: target.id, type: target.type, kind: target.kind };

  targetIdLabel.textContent = target.id.toUpperCase();

  // Classification badge.
  const cls = target.classification || 'hostile';
  if (targetClassificationEl) {
    const CLS_LABELS = { hostile: 'HOSTILE', friendly: 'FRIENDLY', neutral: 'NEUTRAL', unknown: 'UNKNOWN' };
    targetClassificationEl.textContent   = CLS_LABELS[cls] || cls.toUpperCase();
    targetClassificationEl.style.display = '';
    targetClassificationEl.style.color   = CONTACT_COLORS[cls] || 'var(--primary)';
  }

  // Advisory text for non-hostile contacts.
  if (targetAdvisoryEl) {
    if (cls === 'unknown') {
      targetAdvisoryEl.textContent   = 'UNIDENTIFIED — recommend Science scan before engagement';
      targetAdvisoryEl.style.display = '';
      targetAdvisoryEl.style.color   = 'var(--warning)';
    } else if (cls === 'neutral') {
      targetAdvisoryEl.textContent   = 'NEUTRAL CONTACT — engagement may cause diplomatic incident';
      targetAdvisoryEl.style.display = '';
      targetAdvisoryEl.style.color   = 'var(--warning)';
    } else {
      targetAdvisoryEl.textContent   = '';
      targetAdvisoryEl.style.display = 'none';
    }
  }

  // Shield frequency (revealed by science scan, enemy contacts only).
  if (target.shield_frequency && shieldFreqRowEl && shieldFreqEl) {
    const freq     = target.shield_frequency.toUpperCase();
    const isMatch  = target.shield_frequency === currentFrequency;
    shieldFreqRowEl.style.display = '';
    shieldFreqEl.textContent      = freq;
    shieldFreqEl.style.color      = isMatch ? 'var(--primary)' : 'var(--warning)';
  } else if (shieldFreqRowEl) {
    shieldFreqRowEl.style.display = 'none';
  }

  const kind = target.kind || 'enemy';

  if (kind === 'station') {
    // Stations always have full data.
    const hullPct = Math.max(0, (target.hull / (target.hull_max || 100)) * 100);
    targetHullFill.style.width      = `${hullPct}%`;
    targetHullText.textContent      = `${Math.round(target.hull)}`;
    targetShieldFwdFill.style.width = '0%';
    targetShieldFwdText.textContent = '—';
    targetShieldAftFill.style.width = '0%';
    targetShieldAftText.textContent = '—';
    targetTypeEl.textContent        = (target.station_type || 'STATION').toUpperCase();
  } else if (kind === 'creature') {
    const hullPct = Math.max(0, target.hull / 100 * 100);
    targetHullFill.style.width      = `${hullPct}%`;
    targetHullText.textContent      = `${Math.round(target.hull)}`;
    targetShieldFwdFill.style.width = '0%';
    targetShieldFwdText.textContent = '—';
    targetShieldAftFill.style.width = '0%';
    targetShieldAftText.textContent = '—';
    targetTypeEl.textContent        = (target.creature_type || 'CREATURE').toUpperCase();
  } else if (target.scan_state === 'scanned') {
    // Scanned enemy — full data.
    const MAX_HULL = { scout: 40, cruiser: 70, destroyer: 100 };
    const maxHull  = MAX_HULL[target.type] ?? 100;
    const hullPct  = Math.max(0, (target.hull / maxHull) * 100);
    targetHullFill.style.width      = `${hullPct}%`;
    targetHullText.textContent      = `${Math.round(target.hull)}`;
    targetShieldFwdFill.style.width = `${Math.max(0, target.shield_front)}%`;
    targetShieldFwdText.textContent = `${Math.round(target.shield_front)}`;
    targetShieldAftFill.style.width = `${Math.max(0, target.shield_rear)}%`;
    targetShieldAftText.textContent = `${Math.round(target.shield_rear)}`;
    targetTypeEl.textContent        = target.type.toUpperCase();
  } else {
    // Unscanned enemy — no scan data yet.
    targetHullFill.style.width      = '0%';
    targetHullText.textContent      = '—';
    targetShieldFwdFill.style.width = '0%';
    targetShieldFwdText.textContent = '—';
    targetShieldAftFill.style.width = '0%';
    targetShieldAftText.textContent = '—';
    targetTypeEl.textContent        = 'UNKNOWN';
  }

  if (shipState) {
    const dx   = target.x - shipState.position.x;
    const dy   = target.y - shipState.position.y;
    const dist = Math.hypot(dx, dy);
    const brg  = ((Math.atan2(dx, -dy) * 180 / Math.PI) + 360) % 360;
    targetRange.textContent   = `${(dist / 1000).toFixed(1)}km`;
    targetBearing.textContent = `${Math.round(brg).toString().padStart(3,'0')}°`;

    // Beam arc check (client-side for status display).
    const BEAM_RANGE = shipState.beam_range ?? 8_000;
    const ARC        = shipState.beam_arc_deg ?? 45;
    const shipHead   = shipState.heading;
    const diff       = Math.abs(((brg - shipHead + 180 + 360) % 360) - 180);
    if (dist > BEAM_RANGE) {
      beamStatus.textContent = 'OUT OF RANGE';
      beamFireBtn.disabled   = false;
    } else if (diff > ARC) {
      beamStatus.textContent = 'OUT OF ARC';
      beamFireBtn.disabled   = false;
    } else {
      beamStatus.textContent = 'IN ARC';
      beamFireBtn.disabled   = false;
    }
  }
}

function updateTubeUI(state) {
  const cooldowns     = state.tube_cooldowns   ?? [0, 0];
  const serverTypes   = state.tube_types       || tubeTypes;
  const serverLoading = state.tube_loading     || tubeLoading;
  const reloadRefs    = state.tube_reload_times || tubeReloadTimes;

  // Header ammo label: total ammo across all types.
  const totalAmmo = Object.values(torpedoAmmo).reduce((s, v) => s + v, 0);
  ammoLabel.textContent = `AMMO: ${totalAmmo}`;

  _updateSingleTube(1, cooldowns[0] ?? 0, serverTypes[0], serverLoading[0] ?? 0, reloadRefs[0] ?? 3.0);
  _updateSingleTube(2, cooldowns[1] ?? 0, serverTypes[1], serverLoading[1] ?? 0, reloadRefs[1] ?? 3.0);
}

function _updateSingleTube(tubeNum, cooldown, tType, loadTimer, reloadRef) {
  const reloadFill = document.getElementById(`tube${tubeNum}-reload-fill`);
  const statusEl   = document.getElementById(`tube${tubeNum}-status`);
  const fireBtn    = document.getElementById(`tube${tubeNum}-fire-btn`);
  if (!reloadFill || !statusEl || !fireBtn) return;

  const isLoading    = loadTimer > 0;
  const isReloading  = cooldown  > 0;
  const authPending  = pendingAuth[tubeNum - 1] !== null;
  const typeAmmo     = torpedoAmmo[tType] ?? 0;

  let pct, statusText, disabled;

  if (isLoading) {
    pct        = Math.max(0, (1 - loadTimer / TUBE_LOAD_TIME) * 100);
    statusText = `LOADING ${TYPE_ABBREV[tType] || (tType || '').toUpperCase()}`;
    disabled   = true;
  } else if (isReloading) {
    const refTime = reloadRef > 0 ? reloadRef : (TYPE_RELOAD_TIMES[tType] ?? 5.0);
    pct        = Math.max(0, (1 - cooldown / refTime) * 100);
    statusText = 'RELOADING';
    disabled   = true;
  } else if (authPending) {
    pct        = 100;
    statusText = 'AWAITING AUTH';
    disabled   = true;
  } else {
    pct        = 100;
    statusText = 'READY';
    disabled   = typeAmmo <= 0;
  }

  reloadFill.style.width = `${pct}%`;
  statusEl.textContent   = statusText;
  fireBtn.disabled       = disabled;

  // Colour the fill by torpedo type.
  const col = TYPE_COLORS[tType] || TYPE_COLORS.standard;
  reloadFill.style.backgroundColor = col;

  // Show type badge next to tube label.
  const typeEl = document.getElementById(`tube${tubeNum}-type`);
  if (typeEl) {
    typeEl.textContent  = TYPE_ABBREV[tType] || (tType || 'STD').toUpperCase();
    typeEl.style.color  = col;
  }
}

function updateMagazinePanel() {
  const panelEl = document.getElementById('magazine-panel');
  if (!panelEl) return;
  panelEl.innerHTML = TORPEDO_TYPES.map(t => {
    const cur = torpedoAmmo[t] ?? 0;
    const max = torpedoAmmoMax[t] ?? 0;
    if (max === 0) return '';
    const col  = TYPE_COLORS[t] || '#888';
    const abbr = TYPE_ABBREV[t] || t.toUpperCase();
    const pct  = max > 0 ? Math.round((cur / max) * 100) : 0;
    return `<div class="mag-type" style="border-color:${col}">
      <span class="mag-abbr" style="color:${col}">${abbr}</span>
      <span class="mag-count">${cur}/${max}</span>
      <div class="mag-bar"><div class="mag-fill" style="width:${pct}%;background:${col}"></div></div>
    </div>`;
  }).join('');
}

function _suggestTorpedoType() {
  const target = contacts.find(c => c.id === selectedId);
  if (!target) return null;
  const kind = target.kind || 'enemy';

  // Station targets: heavy (they don't maneuver).
  if (kind === 'station' && (torpedoAmmo.heavy ?? 0) > 0) return 'heavy';

  // High shields: piercing bypasses 75%, ion drains.
  if (target.scan_state === 'scanned') {
    const totalShield = (target.shield_front ?? 0) + (target.shield_rear ?? 0);
    if (totalShield > 60) {
      if ((torpedoAmmo.piercing ?? 0) > 0) return 'piercing';
      if ((torpedoAmmo.ion ?? 0) > 0) return 'ion';
    }
  }

  // Fast ships (scouts): homing tracks them.
  if (target.type === 'scout' && (torpedoAmmo.homing ?? 0) > 0) return 'homing';

  // Default: standard if available.
  if ((torpedoAmmo.standard ?? 0) > 0) return 'standard';
  return null;
}

function _updateLoadButtons() {
  const btns = document.getElementById('tube-load-btns');
  if (!btns) return;
  const suggested = _suggestTorpedoType();

  btns.querySelectorAll('.load-btn').forEach(btn => {
    const t     = btn.dataset.type;
    const count = torpedoAmmo[t] ?? 0;
    const max   = torpedoAmmoMax[t] ?? 0;

    // Update count badge.
    const countEl = btn.querySelector('.load-btn-count');
    if (countEl) countEl.textContent = `${count}`;

    // Disable if empty.
    btn.disabled = count <= 0;

    // Hide button entirely if ship carries none of this type.
    btn.style.display = (max === 0) ? 'none' : '';

    // Highlight suggested type.
    btn.classList.toggle('load-btn--suggested', t === suggested);
  });
}

// ---------------------------------------------------------------------------
// Radar rendering
// ---------------------------------------------------------------------------

function resizeRadar() {
  const wrap = radarCanvas.parentElement;
  const size = Math.min(wrap.clientWidth, wrap.clientHeight);
  radarCanvas.width  = wrap.clientWidth;
  radarCanvas.height = wrap.clientHeight;
}

function renderLoop() {
  if (!gameActive) return;
  drawRadar(performance.now());
  requestAnimationFrame(renderLoop);
}

function drawRadar(now) {
  if (!radarCtx || !shipState || !radarRenderer) return;

  // MapRenderer draws: background, range rings, contacts (with cadet hint via drawContact),
  // torpedo trails, ship chevron, beam flash.
  radarRenderer.render(now);

  const ctx = radarCtx;
  const cw  = radarCanvas.width;
  const ch  = radarCanvas.height;
  const cx  = cw / 2;
  const cy  = ch / 2;

  // Station-specific overlays drawn on top:

  // Beam arc (dynamic range + arc from ship state).
  const ARC_DEG = shipState.beam_arc_deg ?? 45;
  const headRad = shipState.heading * Math.PI / 180;
  const zoom    = radarRenderer.getZoom();
  const arcR    = (shipState.beam_range ?? 10_000) / zoom;
  const upAngle = -Math.PI / 2;
  const leftArc  = upAngle - ARC_DEG * Math.PI / 180;
  const rightArc = upAngle + ARC_DEG * Math.PI / 180;

  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(headRad);
  ctx.fillStyle = 'rgba(0, 255, 65, 0.05)';
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.arc(0, 0, arcR, leftArc, rightArc);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = C_PRIMARY_DIM;
  ctx.lineWidth   = 1;
  ctx.beginPath();
  ctx.moveTo(0, 0); ctx.lineTo(Math.cos(leftArc) * arcR, Math.sin(leftArc) * arcR);
  ctx.moveTo(0, 0); ctx.lineTo(Math.cos(rightArc) * arcR, Math.sin(rightArc) * arcR);
  ctx.stroke();
  ctx.restore();

  // Torpedo track lines from launch position to current position.
  _drawTorpedoTracks(ctx, now);

  // Lead indicator — predicted intercept point for selected target.
  _drawLeadIndicator(ctx, now);

  // Explosions — expanding wireframe circles.
  {
    const done = [];
    for (const exp of explosions) {
      const age = now - exp.startTime;
      if (age >= EXPLOSION_DURATION) { done.push(exp); continue; }
      const t  = age / EXPLOSION_DURATION;
      const sp = radarRenderer.worldToCanvas(exp.x, exp.y);
      ctx.save();
      for (let ring = 0; ring < 3; ring++) {
        const ringT  = Math.min(1, (t + ring * 0.1));
        const radius = ringT * 20 + 2;
        const alpha  = (1 - ringT) * 0.8;
        ctx.strokeStyle = `rgba(255, 64, 64, ${alpha})`;
        ctx.lineWidth   = 1.5;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.restore();
    }
    for (const exp of done) explosions.splice(explosions.indexOf(exp), 1);
  }
}

// ---------------------------------------------------------------------------
// Torpedo track lines — dashed line from launch position to current position
// ---------------------------------------------------------------------------

function _drawTorpedoTracks(ctx) {
  if (!radarRenderer) return;
  ctx.save();
  ctx.lineWidth = 1;
  for (const t of torpedoes) {
    const lp = _torpedoLaunchPos.get(t.id);
    if (!lp) continue;
    const from = radarRenderer.worldToCanvas(lp.x, lp.y);
    const to   = radarRenderer.worldToCanvas(t.x, t.y);
    const isHoming = t.torpedo_type === 'homing';
    ctx.strokeStyle = isHoming ? C_FRIENDLY : 'rgba(0, 255, 65, 0.3)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Lead indicator — predicted intercept point for selected target
// ---------------------------------------------------------------------------

function _drawLeadIndicator(ctx, now) {
  if (!selectedId || !radarRenderer || !shipState) return;
  const target = contacts.find(c => c.id === selectedId);
  if (!target || !target.velocity) return;

  // Target velocity components from heading + speed.
  const hRad = target.heading * Math.PI / 180;
  const tvx  = target.velocity * Math.sin(hRad);
  const tvy  = -target.velocity * Math.cos(hRad);

  // Distance from ship to target.
  const dx   = target.x - shipState.position.x;
  const dy   = target.y - shipState.position.y;
  const dist = Math.hypot(dx, dy);

  // Torpedo speed from currently loaded tube type.
  const torpSpeed = _getTorpedoSpeed();
  if (torpSpeed <= 0) return;

  // Time to intercept (simple linear estimate).
  const toi = dist / torpSpeed;

  // Intercept point.
  const ix = target.x + tvx * toi;
  const iy = target.y + tvy * toi;

  // Draw crosshair at intercept point.
  const sp = radarRenderer.worldToCanvas(ix, iy);
  const r  = 6;
  const pulse = 0.6 + 0.4 * Math.sin(now * 0.005);

  ctx.save();
  ctx.globalAlpha = pulse;
  ctx.strokeStyle = C_PRIMARY;
  ctx.lineWidth   = 1.5;

  // Open circle.
  ctx.beginPath();
  ctx.arc(sp.x, sp.y, r, 0, Math.PI * 2);
  ctx.stroke();

  // Cross lines.
  const arm = r + 4;
  ctx.beginPath();
  ctx.moveTo(sp.x - arm, sp.y); ctx.lineTo(sp.x - r, sp.y);
  ctx.moveTo(sp.x + r, sp.y);   ctx.lineTo(sp.x + arm, sp.y);
  ctx.moveTo(sp.x, sp.y - arm); ctx.lineTo(sp.x, sp.y - r);
  ctx.moveTo(sp.x, sp.y + r);   ctx.lineTo(sp.x, sp.y + arm);
  ctx.stroke();

  // Label.
  ctx.font      = '9px monospace';
  ctx.fillStyle = C_PRIMARY;
  ctx.fillText('LEAD', sp.x + arm + 3, sp.y + 3);

  ctx.restore();
}

function _getTorpedoSpeed() {
  // Use first tube's loaded type to determine torpedo speed for lead calc.
  const type = tubeTypes[0] || 'standard';
  return TYPE_VELOCITY[type] || 500;
}

// ---------------------------------------------------------------------------
// Enemy wireframe shapes (station-specific, NOT in renderer.js)
// ---------------------------------------------------------------------------

function drawEnemyShape(ctx, sx, sy, type, halfSize, color, selected) {
  ctx.save();
  ctx.translate(sx, sy);
  ctx.strokeStyle = color;
  ctx.lineWidth   = selected ? 2 : 1.5;

  if (type === 'scout') {
    // Diamond (4 lines)
    const s = halfSize;
    ctx.beginPath();
    ctx.moveTo(0, -s);
    ctx.lineTo(s, 0);
    ctx.lineTo(0, s);
    ctx.lineTo(-s, 0);
    ctx.closePath();
    ctx.stroke();
  } else if (type === 'cruiser') {
    // Equilateral triangle
    const s = halfSize;
    ctx.beginPath();
    ctx.moveTo(0, -s);
    ctx.lineTo(s * 0.866, s * 0.5);
    ctx.lineTo(-s * 0.866, s * 0.5);
    ctx.closePath();
    ctx.stroke();
  } else if (type === 'destroyer') {
    // Hexagon
    const s = halfSize;
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = (i * Math.PI) / 3 - Math.PI / 6;
      if (i === 0) ctx.moveTo(Math.cos(a) * s, Math.sin(a) * s);
      else         ctx.lineTo(Math.cos(a) * s, Math.sin(a) * s);
    }
    ctx.closePath();
    ctx.stroke();
  } else {
    // Unknown / unscanned — generic circle blip.
    ctx.beginPath();
    ctx.arc(0, 0, halfSize * 0.7, 0, Math.PI * 2);
    ctx.stroke();
  }

  // Selected target: outer glow ring.
  if (selected) {
    ctx.strokeStyle = C_FRIENDLY;
    ctx.lineWidth   = 1;
    ctx.beginPath();
    ctx.arc(0, 0, halfSize + 6, 0, Math.PI * 2);
    ctx.stroke();
  }

  ctx.restore();
}

// Station — square with protruding crosshair lines.
function drawStationShape(ctx, sx, sy, color, selected) {
  ctx.save();
  ctx.translate(sx, sy);
  ctx.strokeStyle = color;
  ctx.lineWidth   = selected ? 2 : 1.5;
  const s = 8;
  ctx.beginPath();
  ctx.rect(-s, -s, s * 2, s * 2);
  ctx.stroke();
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(-s - 4, 0); ctx.lineTo(s + 4, 0);
  ctx.moveTo(0, -s - 4); ctx.lineTo(0, s + 4);
  ctx.stroke();
  if (selected) {
    ctx.strokeStyle = C_FRIENDLY;
    ctx.lineWidth   = 1;
    ctx.beginPath();
    ctx.arc(0, 0, s + 8, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}

// Creature — organic trefoil shape in magenta.
function drawCreatureShape(ctx, sx, sy, color, selected) {
  ctx.save();
  ctx.translate(sx, sy);
  const cr = 7;
  ctx.strokeStyle = '#ff44ff';
  ctx.lineWidth   = selected ? 2.5 : 1.5;
  ctx.beginPath();
  for (let i = 0; i < 3; i++) {
    const a = (i * Math.PI * 2) / 3 - Math.PI / 2;
    const lx = Math.cos(a) * cr * 0.45;
    const ly = Math.sin(a) * cr * 0.45;
    ctx.moveTo(lx + cr * 0.55, ly);
    ctx.arc(lx, ly, cr * 0.55, 0, Math.PI * 2);
  }
  ctx.stroke();
  ctx.fillStyle = '#ff44ff';
  ctx.beginPath();
  ctx.arc(0, 0, 2, 0, Math.PI * 2);
  ctx.fill();
  if (selected) {
    ctx.strokeStyle = C_FRIENDLY;
    ctx.lineWidth   = 1;
    ctx.beginPath();
    ctx.arc(0, 0, cr + 6, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Range control
// ---------------------------------------------------------------------------

function _onRangeChange(key, worldUnits) {
  if (!radarRenderer) return;
  radarRenderer.setRange(worldUnits);
  _updateWeaponRangeRings();
}

/** Update range rings showing beam range, torpedo range. */
function _updateWeaponRangeRings() {
  if (!radarRenderer) return;
  const beamRange = (shipState && shipState.beam_range) ? shipState.beam_range : 10_000;
  radarRenderer.setRangeRings([
    { range: beamRange, label: 'BEAM', style: 'dotted' },
    { range: 20_000,    label: 'TORP', style: 'dashed' },
  ]);
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
