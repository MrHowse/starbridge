/**
 * Electronic Warfare Station — ew.js
 *
 * Displays:
 *   - ECM tactical map: ship at centre, enemy contacts, active jam range circle
 *   - Enemy cards with jam_factor bars (click to set as jam target)
 *   - Countermeasure charge/toggle controls
 *   - Network intrusion puzzle launch
 *
 * Receives: ew.state, ship.state (for ecm_suite power), game.started
 * Sends: ew.set_jam_target, ew.toggle_countermeasures, ew.begin_intrusion
 *        plus shared puzzle messages (puzzle.submit, puzzle.cancel, etc.)
 */

import { initConnection } from '../shared/connection.js';
import { initPuzzleRenderer } from '../shared/puzzle_renderer.js';
import { initRoleBar } from '../shared/role_bar.js';
import { initCrewRoster } from '../shared/crew_roster.js';
import { SoundBank } from '../shared/audio.js';
import '../shared/audio_ambient.js';
import '../shared/audio_events.js';
import { wireButtonSounds } from '../shared/audio_ui.js';
import { RangeControl, STATION_RANGES } from '../shared/range_control.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

let _mapWorldRadius = 30_000;
let _ewRangeControl = null;
const PLAYER_COLOUR    = '#00c87a';
const ENEMY_COLOUR     = '#ff5050';
const JAM_COLOUR       = '#f0c040';
const INTRUDED_COLOUR  = '#80a0ff';
const CREATURE_COLOUR  = '#00ffaa';

// Creature types that support EW interactions
const SEDATABLE_TYPES = new Set(['rift_stalker']);
const DISRUPTABLE_TYPES = new Set(['swarm']);

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _ewState   = null;
let _shipState = null;
let _send      = null;   // WebSocket send function, captured after connect

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

let canvas, ctx;

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  // Wire DOM
  canvas = document.getElementById('ew-canvas');
  ctx    = canvas.getContext('2d');

  const { send } = initConnection({
    role: 'electronic_warfare',
    onStatusChange: (connected) => {
      document.querySelector('[data-status-dot]').className =
        'status-dot ' + (connected ? 'status-dot--connected' : 'status-dot--disconnected');
      document.querySelector('[data-status-label]').textContent =
        connected ? 'CONNECTED' : 'DISCONNECTED';
    },
    onMessage: handleMessage,
  });

  _send = send;
  initPuzzleRenderer(send);
  initRoleBar(send, 'electronic_warfare');
  initCrewRoster(send);
  SoundBank.init();
  wireButtonSounds(SoundBank);

  // Canvas click — select jam target
  canvas.addEventListener('click', (e) => {
    const rect = canvas.getBoundingClientRect();
    const relX = e.clientX - rect.left;
    const relY = e.clientY - rect.top;
    handleCanvasClick(relX, relY);
  });

  // Countermeasure toggle
  document.getElementById('btn-cm-toggle').addEventListener('click', () => {
    if (!_ewState) return;
    const newActive = !_ewState.countermeasures_active;
    send('ew.toggle_countermeasures', { active: newActive });
  });

  // Begin intrusion
  document.getElementById('btn-intrusion').addEventListener('click', () => {
    if (!_ewState || !_ewState.jam_target_id) return;
    const targetSystem = document.getElementById('intrusion-system').value;
    send('ew.begin_intrusion', {
      entity_id: _ewState.jam_target_id,
      target_system: targetSystem,
    });
  });

  // Range control
  const rangeBarEl = document.getElementById('range-bar');
  if (rangeBarEl) {
    const cfg = STATION_RANGES.electronic_warfare;
    _ewRangeControl = new RangeControl({
      container:    rangeBarEl,
      stationId:    'electronic_warfare',
      ranges:       cfg.available,
      defaultRange: cfg.default,
      onChange:      (key, worldUnits) => { _mapWorldRadius = worldUnits; },
    });
    _ewRangeControl.attach();
    _mapWorldRadius = _ewRangeControl.currentRangeUnits();
  }

  // Canvas resize
  const ro = new ResizeObserver(resizeCanvas);
  ro.observe(canvas.parentElement);
  resizeCanvas();

  // Render loop
  requestAnimationFrame(renderLoop);
});

// ---------------------------------------------------------------------------
// Message routing
// ---------------------------------------------------------------------------

function handleMessage(msg) {
  switch (msg.type) {
    case 'game.started':
      showStation(msg.payload.mission_name || 'ACTIVE MISSION', msg.payload.ship_class || '');
      SoundBank.setAmbient('life_support', { active: true });
      break;
    case 'game.over':
      document.querySelector('[data-standby]').style.display = 'flex';
      document.querySelector('[data-ew-main]').style.display  = 'none';
      SoundBank.play(msg.payload.result === 'victory' ? 'victory' : 'defeat');
      SoundBank.stopAmbient('life_support');
      SoundBank.stopAmbient('alert_level');
      break;
    case 'ship.alert_changed':
      SoundBank.setAmbient('alert_level', { level: msg.payload.level });
      break;
    case 'ship.hull_hit':
      SoundBank.play('hull_hit');
      break;
    case 'ew.state': {
      const prevTarget = _ewState?.jam_target_id;
      _ewState = msg.payload;
      updateControls();
      updateEnemyList();
      updateCreatureList();
      // Play lock sound when jam target first acquired.
      if (msg.payload.jam_target_id && msg.payload.jam_target_id !== prevTarget) {
        SoundBank.play('scan_complete');
      }
      break;
    }
    case 'ship.state':
      _shipState = msg.payload;
      break;
  }
}

// ---------------------------------------------------------------------------
// UI update helpers
// ---------------------------------------------------------------------------

function showStation(missionName, shipClass) {
  document.querySelector('[data-standby]').style.display = 'none';
  document.querySelector('[data-ew-main]').style.display = 'grid';
  document.getElementById('mission-label').textContent = missionName.toUpperCase();

  // Ship-class-specific panels
  const stealthPanel = document.getElementById('stealth-panel');
  const advEcmPanel  = document.getElementById('advanced-ecm-panel');
  if (stealthPanel) stealthPanel.style.display = shipClass === 'scout' ? '' : 'none';
  if (advEcmPanel)  advEcmPanel.style.display  = shipClass === 'corvette' ? '' : 'none';
}

function updateControls() {
  if (!_ewState) return;

  // ECM efficiency & range
  const eff = _ewState.ecm_efficiency || 0;
  document.getElementById('ecm-efficiency').textContent = (eff * 100).toFixed(0) + '%';
  const effRange = _ewState.effective_jam_range || 0;
  document.getElementById('ecm-range-label').textContent = `JAM RANGE: ${Math.round(effRange).toLocaleString()}`;

  // Jam target info
  const jamTarget = _ewState.jam_target_id || null;
  const jamEl     = document.getElementById('jam-target-label');
  const gaugeJam  = document.getElementById('jam-gauge');
  const pctJam    = document.getElementById('jam-pct');

  if (jamTarget) {
    const enemy = (_ewState.enemies || []).find(e => e.id === jamTarget);
    const jam = enemy ? enemy.jam_factor : 0;
    jamEl.textContent    = jamTarget.toUpperCase();
    gaugeJam.style.width = Math.min(100, jam / 0.8 * 100).toFixed(1) + '%';
    pctJam.textContent   = Math.round(jam * 100) + '%';
  } else {
    jamEl.textContent    = 'NONE';
    gaugeJam.style.width = '0%';
    pctJam.textContent   = '0%';
  }

  // Countermeasures
  const cmActive  = _ewState.countermeasures_active;
  const cmCharges = _ewState.countermeasure_charges ?? 0;
  const labelCm   = document.getElementById('cm-active-label');
  const gaugeCm   = document.getElementById('cm-gauge');
  const labelCmC  = document.getElementById('cm-charges');
  const btnCm     = document.getElementById('btn-cm-toggle');

  labelCm.textContent    = cmActive ? 'ACTIVE' : 'INACTIVE';
  labelCm.style.color    = cmActive ? 'var(--warning)' : 'var(--text-muted)';
  gaugeCm.style.width    = (cmCharges / 10 * 100).toFixed(0) + '%';
  labelCmC.textContent   = cmCharges;
  btnCm.textContent      = cmActive ? 'DISABLE COUNTERMEASURES' : 'ENABLE COUNTERMEASURES';
  btnCm.className        = 'ew-btn' + (cmActive ? ' ew-btn--active' : '');
  btnCm.disabled         = (cmCharges === 0 && !cmActive);

  // Intrusion target
  const intTarget = _ewState.intrusion_target_id;
  const intSystem = _ewState.intrusion_target_system;
  const labelInt  = document.getElementById('intrusion-target-label');
  labelInt.textContent = (intTarget && intSystem)
    ? `${intTarget.toUpperCase()} / ${intSystem.toUpperCase()}`
    : 'NO TARGET';
  document.getElementById('btn-intrusion').disabled = !jamTarget;
}

function updateEnemyList() {
  if (!_ewState) return;
  const list    = document.getElementById('enemy-list');
  const enemies = _ewState.enemies || [];

  if (enemies.length === 0) {
    list.innerHTML = '<p class="text-dim">No contacts detected.</p>';
    return;
  }

  const jamTarget = _ewState.jam_target_id;
  list.innerHTML = '';

  for (const e of enemies) {
    const isSelected = e.id === jamTarget;
    const isJammed   = e.jam_factor > 0.05;
    const isStunned  = e.intrusion_stun_ticks > 0;
    const jamPct     = Math.round(e.jam_factor * 100);
    const distKm     = (e.distance / 1000).toFixed(1);

    let cardClass = 'ew-enemy-card';
    if (isSelected) cardClass += ' ew-enemy-card--selected';
    else if (isJammed) cardClass += ' ew-enemy-card--jammed';

    const badge = isStunned
      ? ' [STUNNED]'
      : isJammed ? ` [JAM ${jamPct}%]` : '';

    const card = document.createElement('div');
    card.className   = cardClass;
    card.dataset.eid = e.id;
    card.innerHTML   = `
      <div class="ew-enemy-card__header">
        <span class="text-data">${e.id.toUpperCase()}${badge}</span>
        <span class="ew-enemy-card__dist">${distKm}k</span>
      </div>
      <div class="ew-enemy-card__type">${e.type}</div>
      <div class="ew-enemy-card__jam-bar">
        <div class="ew-enemy-card__jam-fill" style="width:${Math.min(100, jamPct / 0.8)}%"></div>
      </div>
    `;

    card.addEventListener('click', () => {
      if (!_send) return;
      const newTarget = isSelected ? null : e.id;
      _send('ew.set_jam_target', { entity_id: newTarget });
    });

    list.appendChild(card);
  }
}

function updateCreatureList() {
  if (!_ewState) return;
  const list = document.getElementById('creature-list');
  const creatures = _ewState.creatures || [];
  const countEl = document.getElementById('creature-count');
  countEl.textContent = creatures.length;

  if (creatures.length === 0) {
    list.innerHTML = '<p class="text-dim">No creatures detected.</p>';
    return;
  }

  list.innerHTML = '';

  for (const c of creatures) {
    const distKm = (c.distance / 1000).toFixed(1);
    const hullPct = c.hull_max > 0 ? Math.round(c.hull / c.hull_max * 100) : 0;
    const typeName = c.creature_type.replace(/_/g, ' ').toUpperCase();
    const stateLabel = (c.behaviour_state || 'unknown').toUpperCase();

    const card = document.createElement('div');
    card.className = 'ew-enemy-card';

    let actionsHtml = '';
    if (SEDATABLE_TYPES.has(c.creature_type) && c.behaviour_state !== 'sedated') {
      actionsHtml += `<button class="ew-btn ew-btn--sm" data-sedate="${c.id}">SEDATE</button>`;
    }
    if (DISRUPTABLE_TYPES.has(c.creature_type) && c.behaviour_state !== 'dispersed') {
      actionsHtml += `<button class="ew-btn ew-btn--sm" data-disrupt="${c.id}">DISRUPT</button>`;
    }

    const stateColour = ['attacking', 'aggressive', 'agitated'].includes(c.behaviour_state)
      ? 'var(--danger, #ff4040)'
      : ['sedated', 'dispersed', 'dormant', 'idle'].includes(c.behaviour_state)
        ? 'var(--success, #00c87a)'
        : 'var(--warning, #ffaa00)';

    card.innerHTML = `
      <div class="ew-enemy-card__header">
        <span class="text-data">${c.id.toUpperCase()}</span>
        <span class="ew-enemy-card__dist">${distKm}k</span>
      </div>
      <div class="ew-enemy-card__type">${typeName} — <span style="color:${stateColour}">${stateLabel}</span></div>
      <div class="ew-enemy-card__type" style="opacity:0.6">HULL ${hullPct}%${c.attached ? ' — ATTACHED' : ''}</div>
      ${actionsHtml ? `<div style="margin-top:4px;display:flex;gap:4px">${actionsHtml}</div>` : ''}
    `;

    list.appendChild(card);
  }

  // Wire sedate/disrupt buttons
  list.querySelectorAll('[data-sedate]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (_send) _send('creature.sedate', { creature_id: btn.dataset.sedate });
    });
  });
  list.querySelectorAll('[data-disrupt]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (_send) _send('creature.ew_disrupt', { creature_id: btn.dataset.disrupt });
    });
  });
}

// ---------------------------------------------------------------------------
// Canvas interaction
// ---------------------------------------------------------------------------

function handleCanvasClick(relX, relY) {
  if (!_ewState || !_shipState || !_send) return;
  const ship   = _shipState;
  const sx     = ship.position?.x || 50_000;
  const sy     = ship.position?.y || 50_000;
  const w = canvas.width;
  const h = canvas.height;
  const scale  = Math.min(w, h) / 2 / _mapWorldRadius;

  // Convert canvas click to world offset from ship
  const wOffX  = (relX - w / 2) / scale;
  const wOffY  = (relY - h / 2) / scale;
  const wx     = sx + wOffX;
  const wy     = sy + wOffY;

  // Click threshold in world units (~6% of viewport radius)
  const threshold = _mapWorldRadius * 0.06;
  let nearest = null;
  let nearestDist = Infinity;

  for (const e of (_ewState.enemies || [])) {
    const d = Math.hypot(e.x - wx, e.y - wy);
    if (d < nearestDist && d < threshold) {
      nearestDist = d;
      nearest = e;
    }
  }

  if (nearest) {
    const newTarget = (nearest.id === _ewState.jam_target_id) ? null : nearest.id;
    _send('ew.set_jam_target', { entity_id: newTarget });
  }
}

// ---------------------------------------------------------------------------
// Canvas rendering
// ---------------------------------------------------------------------------

function resizeCanvas() {
  const wrap = canvas.parentElement;
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width  = w;
    canvas.height = h;
  }
}

function renderLoop() {
  requestAnimationFrame(renderLoop);
  drawMap();
}

function drawMap() {
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#0a0f0a';
  ctx.fillRect(0, 0, w, h);

  if (!_ewState || !_shipState) {
    ctx.fillStyle = '#336633';
    ctx.font = '12px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('AWAITING DATA', w / 2, h / 2);
    return;
  }

  const ship  = _shipState;
  const sx    = ship.position?.x || 50_000;
  const sy    = ship.position?.y || 50_000;
  const scale = Math.min(w, h) / 2 / _mapWorldRadius;

  // Background grid rings
  ctx.strokeStyle = '#1a2a1a';
  ctx.lineWidth = 1;
  for (const r of [10_000, 20_000, 30_000]) {
    ctx.beginPath();
    ctx.arc(w / 2, h / 2, r * scale, 0, Math.PI * 2);
    ctx.stroke();
  }

  // Effective jam range ring
  const jamRange = (_ewState.effective_jam_range || 0) * scale;
  if (jamRange > 0) {
    ctx.strokeStyle = 'rgba(240,192,64,0.3)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.arc(w / 2, h / 2, jamRange, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Enemy contacts
  const jamTarget = _ewState.jam_target_id;
  for (const e of (_ewState.enemies || [])) {
    const ex = w / 2 + (e.x - sx) * scale;
    const ey = h / 2 + (e.y - sy) * scale;

    const isSelected = e.id === jamTarget;
    const isStunned  = e.intrusion_stun_ticks > 0;
    const isJammed   = e.jam_factor > 0.05;

    let colour = ENEMY_COLOUR;
    if (isStunned)     colour = INTRUDED_COLOUR;
    else if (isJammed) colour = JAM_COLOUR;

    // Selection ring
    if (isSelected) {
      ctx.strokeStyle = colour;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(ex, ey, 14, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Triangle (pointing up)
    const s = 7;
    ctx.fillStyle = colour;
    ctx.beginPath();
    ctx.moveTo(ex,     ey - s);
    ctx.lineTo(ex + s, ey + s);
    ctx.lineTo(ex - s, ey + s);
    ctx.closePath();
    ctx.fill();

    // Jam arc bar (sweeps clockwise from top)
    if (isJammed || isSelected) {
      const fraction = Math.min(1, e.jam_factor / 0.8);
      ctx.strokeStyle = colour;
      ctx.lineWidth   = 3;
      ctx.beginPath();
      ctx.arc(ex, ey, 16, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * fraction);
      ctx.stroke();
    }

    // Label
    ctx.fillStyle   = colour;
    ctx.font        = '10px monospace';
    ctx.textAlign   = 'center';
    ctx.fillText(e.id.toUpperCase(), ex, ey + s + 13);
  }

  // Creature contacts
  for (const c of (_ewState.creatures || [])) {
    const cx = w / 2 + (c.x - sx) * scale;
    const cy = h / 2 + (c.y - sy) * scale;

    const isHostile = ['attacking', 'aggressive', 'agitated'].includes(c.behaviour_state);
    const colour = isHostile ? '#ff8040' : CREATURE_COLOUR;

    // Circle shape
    ctx.fillStyle = colour;
    ctx.beginPath();
    ctx.arc(cx, cy, 6, 0, Math.PI * 2);
    ctx.fill();

    // Centre dot
    ctx.fillStyle = '#0a0f0a';
    ctx.beginPath();
    ctx.arc(cx, cy, 2, 0, Math.PI * 2);
    ctx.fill();

    // Label
    ctx.fillStyle   = colour;
    ctx.font        = '9px monospace';
    ctx.textAlign   = 'center';
    ctx.fillText(c.creature_type.replace(/_/g, ' ').toUpperCase(), cx, cy + 17);
  }

  // Player ship
  ctx.fillStyle   = PLAYER_COLOUR;
  ctx.beginPath();
  ctx.arc(w / 2, h / 2, 5, 0, Math.PI * 2);
  ctx.fill();

  ctx.strokeStyle = PLAYER_COLOUR;
  ctx.lineWidth   = 1;
  ctx.beginPath();
  ctx.arc(w / 2, h / 2, 10, 0, Math.PI * 2);
  ctx.stroke();

  // North indicator
  ctx.fillStyle = 'rgba(100,160,100,0.6)';
  ctx.font      = '10px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('N', w / 2, 14);
}
