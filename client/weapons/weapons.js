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
 *   weapons.set_shields    { front, rear }
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import { setStatusDot, setAlertLevel, showBriefing, showGameOver } from '../shared/ui_components.js';
import { C_PRIMARY_DIM, C_FRIENDLY } from '../shared/renderer.js';
import { MapRenderer } from '../shared/map_renderer.js';
import { initPuzzleRenderer } from '../shared/puzzle_renderer.js';
import { SoundBank } from '../shared/audio.js';
import '../shared/audio_events.js';
import { wireButtonSounds } from '../shared/audio_ui.js';
import { registerHelp, initHelpOverlay } from '../shared/help_overlay.js';
import { initNotifications } from '../shared/notifications.js';
import { initRoleBar } from '../shared/role_bar.js';

registerHelp([
  { selector: '#radar-canvas',     text: 'Tactical radar — click enemy to select as target.', position: 'right' },
  { selector: '#beam-fire-btn',    text: 'Fire beams — hold for sustained fire within weapon arc.', position: 'left' },
  { selector: '#tube1-fire-btn',   text: 'Fire torpedo tube 1 — needs ammo loaded.', position: 'left' },
  { selector: '#tube2-fire-btn',   text: 'Fire torpedo tube 2 — independent reload timer.', position: 'left' },
  { selector: '#shield-slider',    text: 'Shield balance — slide forward (100%) vs rear (0%).', position: 'above' },
]);

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const RADAR_WORLD_RADIUS  = 15_000;  // world units shown at radar edge
const BEAM_FLASH_MS       = 300;     // beam fire line animation duration
const HIT_FLASH_MS        = 500;     // hull-hit border flash duration
const TORP_RELOAD_TIME    = 5.0;     // must match server TORPEDO_RELOAD_TIME
const TUBE_LOAD_TIME      = 3.0;     // must match server TUBE_LOAD_TIME
const TORPEDO_TYPES       = ['standard', 'emp', 'probe', 'nuclear'];
const TYPE_COLORS         = { standard: '#00ff41', emp: '#00c8ff', probe: '#ffcc00', nuclear: '#ff4040' };
const TRAIL_LENGTH        = 5;       // torpedo trail positions to store
const EXPLOSION_DURATION  = 500;     // explosion ring animation duration ms

// Enemy wireframe sizes (half-size in pixels at radar scale)
const ENEMY_SHAPES = {
  scout:     { size: 8,  color: '#ff4040' },
  cruiser:   { size: 10, color: '#ff4040' },
  destroyer: { size: 13, color: '#ff4040' },
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
const targetIdLabel       = document.getElementById('target-id-label');
const targetHullFill      = document.getElementById('target-hull-fill');
const targetHullText      = document.getElementById('target-hull-text');
const targetShieldFwdFill = document.getElementById('target-shield-fwd-fill');
const targetShieldFwdText = document.getElementById('target-shield-fwd-text');
const targetShieldAftFill = document.getElementById('target-shield-aft-fill');
const targetShieldAftText = document.getElementById('target-shield-aft-text');
const targetRange         = document.getElementById('target-range');
const targetBearing       = document.getElementById('target-bearing');
const targetTypeEl        = document.getElementById('target-type');

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

// Shields
const shieldSlider  = document.getElementById('shield-slider');
const shieldFwdPct  = document.getElementById('shield-fwd-pct');
const shieldAftPct  = document.getElementById('shield-aft-pct');

// ---------------------------------------------------------------------------
// Game state
// ---------------------------------------------------------------------------

let gameActive    = false;
let radarCtx      = null;
let radarRenderer = null;  // MapRenderer instance
let hintsEnabled  = false;  // true when difficulty === 'cadet'

let shipState   = null;   // most recent ship.state payload
let contacts    = [];     // world.entities enemies array
let torpedoes   = [];     // world.entities torpedoes array
let selectedId  = null;   // selected enemy entity_id or null
let suggestedId = null;   // cadet hint: nearest/lowest-hull contact

// Tube state (from ship.state).
let tubeTypes   = ['standard', 'standard'];
let tubeLoading = [0.0, 0.0];

// Pending nuclear auth: request_id for each tube (or null).
let pendingAuth = [null, null];

// Beam frequency selection.
let currentFrequency = 'alpha';

// Beam flash: { targetX, targetY, startTime }
let beamFlash   = null;

// Hull-hit flash timestamp
let hitFlashTime = -Infinity;

// Explosion rings: [{x, y, startTime}]
const explosions = [];

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
  on('captain.authorization_request', handleAuthRequest);
  on('weapons.authorization_result', handleAuthResult);
  on('game.over',                    handleGameOver);

  initPuzzleRenderer(send);
  setupControls();
  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();
  initNotifications(send, 'weapons');
  initRoleBar(send, 'weapons');
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

  requestAnimationFrame(() => {
    radarCtx = radarCanvas.getContext('2d');
    resizeRadar();
    window.addEventListener('resize', resizeRadar);

    // Create MapRenderer for radar (contacts + grid; beam arc drawn separately).
    radarRenderer = new MapRenderer(radarCanvas, {
      range: RADAR_WORLD_RADIUS,
      orientation: 'north-up',
      showGrid: false,
      showRangeRings: true,
      interactive: true,
      zoom: { enabled: false },
      drawContact: (ctx, sx, sy, contact, selected, now) => {
        // Cadet hint pulsing ring before the shape.
        if (hintsEnabled && contact.id === suggestedId && !selected) {
          const pulse = 0.5 + 0.5 * Math.sin(now * 0.004);
          const shape = ENEMY_SHAPES[contact.type] || ENEMY_SHAPES.cruiser;
          ctx.save();
          ctx.strokeStyle = `rgba(255, 176, 0, ${0.5 + 0.4 * pulse})`;
          ctx.lineWidth   = 1.5;
          ctx.setLineDash([4, 4]);
          ctx.beginPath();
          ctx.arc(sx, sy, shape.size + 10, 0, Math.PI * 2);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle  = `rgba(255, 176, 0, ${0.6 + 0.3 * pulse})`;
          ctx.font       = '8px "Share Tech Mono", monospace';
          ctx.textAlign  = 'center';
          ctx.textBaseline = 'bottom';
          ctx.fillText('SUGGESTED TARGET', sx, sy - shape.size - 14);
          ctx.restore();
        }
        drawEnemyShape(ctx, sx, sy, contact.type,
          (ENEMY_SHAPES[contact.type] || ENEMY_SHAPES.cruiser).size,
          '#ff4040', selected);
      },
    });
    radarRenderer.onContactClick((id) => selectTarget(id));

    requestAnimationFrame(renderLoop);
  });

  if (payload.briefing_text) {
    showBriefing(payload.mission_name, payload.briefing_text);
  }

  console.log(`[weapons] Game started — mission: ${payload.mission_id}`);
}

function handleShipState(payload) {
  if (!gameActive) return;
  shipState = payload;
  if (radarRenderer) radarRenderer.updateShipState(payload);
  if (payload.tube_types)   tubeTypes   = payload.tube_types;
  if (payload.tube_loading) tubeLoading = payload.tube_loading;
  updateTubeUI(payload);
}

function handleSensorContacts(payload) {
  if (!gameActive) return;
  contacts  = payload.contacts  || [];
  torpedoes = payload.torpedoes || [];

  // Cadet hint: keep suggestedId pointing at the nearest enemy contact.
  if (hintsEnabled && contacts.length > 0 && shipState) {
    let nearest = null, minDist = Infinity;
    for (const c of contacts) {
      const dx = c.x - shipState.position.x;
      const dy = c.y - shipState.position.y;
      const d  = Math.hypot(dx, dy);
      if (d < minDist) { minDist = d; nearest = c; }
    }
    suggestedId = nearest ? nearest.id : null;
  } else {
    suggestedId = null;
  }

  if (radarRenderer) radarRenderer.updateContacts(contacts, torpedoes);
  updateTargetPanel();
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

  // Shield balance slider.
  shieldSlider.addEventListener('input', () => {
    if (!gameActive) return;
    const v     = parseInt(shieldSlider.value, 10);
    const front = v;
    const rear  = 100 - v;
    shieldFwdPct.textContent = `${front}%`;
    shieldAftPct.textContent = `${rear}%`;
    send('weapons.set_shields', { front: front, rear: rear });
  });

  // Radar click is handled by MapRenderer's onContactClick callback.
}

function _buildLoadControls() {
  // Find the torpedo tubes section and append type-badge elements + load controls.
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

  // Load selector for each tube.
  const loadSection = document.createElement('div');
  loadSection.className = 'tube-load-section';
  loadSection.innerHTML = `
    <div class="text-dim text-label" style="margin-bottom:4px">LOAD TYPE</div>
    <div class="tube-load-row" id="tube-load-btns">
      ${TORPEDO_TYPES.map(t => `
        <button class="load-btn" data-type="${t}" style="border-color:${TYPE_COLORS[t]}"
                title="Load ${t.toUpperCase()} torpedo">
          ${t === 'standard' ? 'STD' : t.toUpperCase()}
        </button>
      `).join('')}
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
  selectedId = id;
  if (radarRenderer) radarRenderer.selectContact(id);
  send('weapons.select_target', { entity_id: id });
  updateTargetPanel();
}

// ---------------------------------------------------------------------------
// UI updates
// ---------------------------------------------------------------------------

function updateTargetPanel() {
  const target = contacts.find(c => c.id === selectedId);

  const shieldFreqRowEl = document.getElementById('target-shield-freq-row');
  const shieldFreqEl    = document.getElementById('target-shield-freq');

  if (!target) {
    targetIdLabel.textContent       = 'NONE';
    targetHullFill.style.width      = '0%';
    targetHullText.textContent      = '—';
    targetShieldFwdFill.style.width = '0%';
    targetShieldFwdText.textContent = '—';
    targetShieldAftFill.style.width = '0%';
    targetShieldAftText.textContent = '—';
    targetRange.textContent         = '—';
    targetBearing.textContent       = '—';
    targetTypeEl.textContent        = '—';
    beamStatus.textContent          = 'NO TARGET';
    beamFireBtn.disabled            = true;
    if (shieldFreqRowEl) shieldFreqRowEl.style.display = 'none';
    return;
  }

  targetIdLabel.textContent = target.id.toUpperCase();

  // Shield frequency (revealed by science scan).
  if (target.shield_frequency && shieldFreqRowEl && shieldFreqEl) {
    const freq     = target.shield_frequency.toUpperCase();
    const isMatch  = target.shield_frequency === currentFrequency;
    shieldFreqRowEl.style.display = '';
    shieldFreqEl.textContent      = freq;
    shieldFreqEl.style.color      = isMatch ? 'var(--primary)' : 'var(--warning)';
  } else if (shieldFreqRowEl) {
    shieldFreqRowEl.style.display = 'none';
  }

  if (target.scan_state === 'scanned') {
    // Max hull by type (from server ENEMY_TYPE_PARAMS).
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
    // Unknown contact — no scan data yet.
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
    const BEAM_RANGE = 8_000;
    const ARC        = 45;
    const shipHead   = shipState.heading;
    const diff       = Math.abs(((brg - shipHead + 180 + 360) % 360) - 180);
    if (dist > BEAM_RANGE) {
      beamStatus.textContent = 'OUT OF RANGE';
      beamFireBtn.disabled   = false;  // still allow fire attempt
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
  const ammo      = state.torpedo_ammo  ?? 0;
  const cooldowns = state.tube_cooldowns ?? [0, 0];
  const serverTypes   = state.tube_types   || tubeTypes;
  const serverLoading = state.tube_loading || tubeLoading;

  ammoLabel.textContent = `AMMO: ${ammo}`;

  _updateSingleTube(1, cooldowns[0] ?? 0, serverTypes[0], serverLoading[0] ?? 0, ammo);
  _updateSingleTube(2, cooldowns[1] ?? 0, serverTypes[1], serverLoading[1] ?? 0, ammo);
}

function _updateSingleTube(tubeNum, cooldown, tType, loadTimer, ammo) {
  const reloadFill = document.getElementById(`tube${tubeNum}-reload-fill`);
  const statusEl   = document.getElementById(`tube${tubeNum}-status`);
  const fireBtn    = document.getElementById(`tube${tubeNum}-fire-btn`);
  if (!reloadFill || !statusEl || !fireBtn) return;

  const isLoading    = loadTimer > 0;
  const isReloading  = cooldown  > 0;
  const authPending  = pendingAuth[tubeNum - 1] !== null;

  let pct, statusText, disabled;

  if (isLoading) {
    pct        = Math.max(0, (1 - loadTimer / TUBE_LOAD_TIME) * 100);
    statusText = `LOADING ${(tType || '').toUpperCase()}`;
    disabled   = true;
  } else if (isReloading) {
    pct        = Math.max(0, (1 - cooldown / TORP_RELOAD_TIME) * 100);
    statusText = 'RELOADING';
    disabled   = true;
  } else if (authPending) {
    pct        = 100;
    statusText = 'AWAITING AUTH';
    disabled   = true;
  } else {
    pct        = 100;
    statusText = 'READY';
    disabled   = ammo <= 0;
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
    typeEl.textContent  = (tType || 'STD').toUpperCase();
    typeEl.style.color  = col;
  }
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

  // Beam arc (±45° from ship heading).
  const ARC_DEG = 45;
  const headRad = shipState.heading * Math.PI / 180;
  const zoom    = radarRenderer.getZoom();
  const arcR    = Math.min(cx, cy) * (8000 / RADAR_WORLD_RADIUS);
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

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
