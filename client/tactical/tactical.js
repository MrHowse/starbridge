/**
 * Tactical Officer Station — tactical.js
 *
 * Displays:
 *   - Tactical plot: annotated north-up canvas map with threat colours,
 *     intercept line, engagement priority rings, and map annotations
 *   - Threat board: enemy contacts with threat ratings + priority controls
 *   - Intercept section: current intercept target, bearing, ETA
 *   - Annotation list: add/remove map markers
 *   - Strike plan builder + executor
 *
 * Receives: tactical.state, ship.state, game.started
 * Sends: tactical.set_engagement_priority, tactical.set_intercept_target,
 *        tactical.add_annotation, tactical.remove_annotation,
 *        tactical.create_strike_plan, tactical.execute_strike_plan
 */

import { initConnection } from '../shared/connection.js';
import { initRoleBar } from '../shared/role_bar.js';
import { SoundBank } from '../shared/audio.js';
import '../shared/audio_ambient.js';
import '../shared/audio_events.js';
import { wireButtonSounds } from '../shared/audio_ui.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAP_WORLD_RADIUS = 100_000;

const THREAT_COLOURS = {
  critical: '#ff5050',
  high:     '#ffa028',
  medium:   '#f0c040',
  low:      '#50a050',
};

const PLAYER_COLOUR = '#00c87a';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _tacState  = null;
let _shipState = null;
let _send      = null;

// Current active map tool: null | 'waypoint' | 'note'
let _activeTool = null;

// Pending strike plan steps (builder)
let _pendingSteps = [];

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

let canvas, ctx;

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  canvas = document.getElementById('tac-canvas');
  ctx    = canvas.getContext('2d');

  const { send } = initConnection({
    role: 'tactical',
    onStatusChange: (connected) => {
      document.querySelector('[data-status-dot]').className =
        'status-dot ' + (connected ? 'status-dot--connected' : 'status-dot--disconnected');
      document.querySelector('[data-status-label]').textContent =
        connected ? 'CONNECTED' : 'DISCONNECTED';
    },
    onMessage: handleMessage,
  });

  _send = send;
  initRoleBar(send, 'tactical');
  SoundBank.init();
  wireButtonSounds(SoundBank);

  // Canvas click — map interaction
  canvas.addEventListener('click', (e) => {
    const rect = canvas.getBoundingClientRect();
    handleCanvasClick(e.clientX - rect.left, e.clientY - rect.top);
  });

  // Toolbar buttons
  document.getElementById('btn-add-waypoint').addEventListener('click', () => setTool('waypoint'));
  document.getElementById('btn-add-note').addEventListener('click', () => setTool('note'));
  document.getElementById('btn-cancel-tool').addEventListener('click', () => setTool(null));

  // Strike plan step builder
  document.getElementById('btn-add-step').addEventListener('click', addPendingStep);
  document.getElementById('btn-create-plan').addEventListener('click', createStrikePlan);

  // Canvas resize
  const ro = new ResizeObserver(resizeCanvas);
  ro.observe(canvas.parentElement);
  resizeCanvas();

  requestAnimationFrame(renderLoop);
});

// ---------------------------------------------------------------------------
// Message routing
// ---------------------------------------------------------------------------

function handleMessage(msg) {
  switch (msg.type) {
    case 'game.started':
      showStation(msg.payload.mission_name || 'ACTIVE MISSION');
      SoundBank.setAmbient('life_support', { active: true });
      break;
    case 'game.over':
      document.querySelector('[data-standby]').style.display = 'flex';
      document.querySelector('[data-tac-main]').style.display = 'none';
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
    case 'ship.system_damaged':
      SoundBank.play('system_damage');
      break;
    case 'tactical.state': {
      const prevCritical = (_tacState?.enemies || []).filter(e => e.threat_level === 'critical').length;
      _tacState = msg.payload;
      updateThreatList();
      updateInterceptPanel();
      updateAnnotationList();
      updateStrikePlans();
      const newCritical = (msg.payload.enemies || []).filter(e => e.threat_level === 'critical').length;
      if (newCritical > prevCritical) SoundBank.play('system_damage');
      break;
    }
    case 'ship.state':
      _shipState = msg.payload;
      break;
  }
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

function showStation(missionName) {
  document.querySelector('[data-standby]').style.display = 'none';
  document.querySelector('[data-tac-main]').style.display = 'grid';
  document.getElementById('mission-label').textContent = missionName.toUpperCase();
}

function setTool(tool) {
  _activeTool = tool;
  document.getElementById('btn-add-waypoint').classList.toggle('tac-tool-btn--active', tool === 'waypoint');
  document.getElementById('btn-add-note').classList.toggle('tac-tool-btn--active', tool === 'note');
  canvas.style.cursor = tool ? 'cell' : 'crosshair';
}

function updateThreatList() {
  if (!_tacState) return;
  const list    = document.getElementById('threat-list');
  const enemies = _tacState.enemies || [];

  if (enemies.length === 0) {
    list.innerHTML = '<p class="text-dim">No contacts detected.</p>';
    return;
  }

  list.innerHTML = '';
  for (const e of enemies) {
    const threat   = e.threat_level || 'low';
    const priority = e.engagement_priority;
    const distKm   = (e.distance / 1000).toFixed(1);

    const card = document.createElement('div');
    card.className = 'tac-threat-card';
    card.innerHTML = `
      <div class="tac-threat-card__header">
        <span class="text-data">${e.id.toUpperCase()}</span>
        <span class="tac-threat-card__dist">${distKm}k</span>
      </div>
      <div class="tac-threat-card__body">
        <span class="tac-threat-badge tac-threat-badge--${threat}">${threat.toUpperCase()}</span>
        ${priority ? `<span class="tac-priority-badge tac-priority-badge--${priority}">${priority.toUpperCase()}</span>` : ''}
        <span class="text-dim" style="font-size:0.7rem">${e.type} · ${e.ai_state}</span>
      </div>
      <div class="tac-threat-card__actions">
        <button class="tac-prio-btn ${priority === 'primary'   ? 'tac-prio-btn--active' : ''}" data-prio="primary">PRIMARY</button>
        <button class="tac-prio-btn ${priority === 'secondary' ? 'tac-prio-btn--active' : ''}" data-prio="secondary">2ND</button>
        <button class="tac-prio-btn ${priority === 'ignore'    ? 'tac-prio-btn--active' : ''}" data-prio="ignore">IGNORE</button>
        <button class="tac-prio-btn" data-prio="intercept" title="Set as intercept target">INTCPT</button>
      </div>
    `;

    card.querySelectorAll('[data-prio]').forEach(btn => {
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const prio = btn.dataset.prio;
        if (prio === 'intercept') {
          const newTarget = (_tacState.intercept_target_id === e.id) ? null : e.id;
          _send('tactical.set_intercept_target', { entity_id: newTarget });
        } else {
          const newPrio = (priority === prio) ? null : prio;
          _send('tactical.set_engagement_priority', { entity_id: e.id, priority: newPrio });
        }
      });
    });

    list.appendChild(card);
  }
}

function updateInterceptPanel() {
  if (!_tacState) return;
  const targetId = _tacState.intercept_target_id;
  document.getElementById('intercept-target-label').textContent =
    targetId ? targetId.toUpperCase() : 'NONE';
  document.getElementById('intercept-bearing').textContent =
    _tacState.intercept_bearing != null ? _tacState.intercept_bearing.toFixed(0) + '\u00b0' : '\u2014';
  document.getElementById('intercept-eta').textContent =
    _tacState.intercept_eta_s != null ? _tacState.intercept_eta_s.toFixed(0) + 's' : '\u2014';
}

function updateAnnotationList() {
  if (!_tacState) return;
  const list = document.getElementById('annotation-list');
  const anns = _tacState.annotations || [];

  if (anns.length === 0) {
    list.innerHTML = '<p class="text-dim">No annotations.</p>';
    return;
  }

  list.innerHTML = '';
  for (const a of anns) {
    const item = document.createElement('div');
    item.className = 'tac-annotation-item';
    const label = a.label || a.text || a.type;
    item.innerHTML = `
      <span class="text-data">${a.type.toUpperCase()}</span>
      <span class="text-dim" style="flex:1;padding:0 6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${label}</span>
      <button class="tac-annotation-item__remove" data-ann-id="${a.id}">\u2715</button>
    `;
    item.querySelector('[data-ann-id]').addEventListener('click', () => {
      _send('tactical.remove_annotation', { annotation_id: a.id });
    });
    list.appendChild(item);
  }
}

function updateStrikePlans() {
  if (!_tacState) return;
  const planList = document.getElementById('plan-list');
  const plans = _tacState.strike_plans || [];

  planList.innerHTML = '';
  for (const p of plans) {
    const card = document.createElement('div');
    card.className = 'tac-plan-card' + (p.executing ? ' tac-plan-card--executing' : '');
    card.innerHTML = `
      <div class="tac-plan-card__header">
        <span class="text-data">${p.plan_id.toUpperCase()}</span>
        <span class="text-dim">${p.steps.length} step${p.steps.length !== 1 ? 's' : ''}</span>
        ${!p.executing
          ? `<button class="tac-tool-btn" data-execute="${p.plan_id}">EXECUTE</button>`
          : '<span style="color:var(--warning)">EXECUTING</span>'}
      </div>
    `;
    const btn = card.querySelector('[data-execute]');
    if (btn) {
      btn.addEventListener('click', () => {
        _send('tactical.execute_strike_plan', { plan_id: p.plan_id });
      });
    }
    planList.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// Strike plan builder
// ---------------------------------------------------------------------------

function addPendingStep() {
  const role   = document.getElementById('step-role').value.trim();
  const action = document.getElementById('step-action').value.trim();
  const offset = parseFloat(document.getElementById('step-offset').value) || 0;
  if (!role || !action) return;

  _pendingSteps.push({ role, action, offset_s: offset });
  document.getElementById('step-role').value   = '';
  document.getElementById('step-action').value = '';
  document.getElementById('step-offset').value = '0';
  renderPendingSteps();
}

function renderPendingSteps() {
  const list = document.getElementById('step-list');
  list.innerHTML = '';
  for (const s of _pendingSteps) {
    const item = document.createElement('div');
    item.className = 'tac-step-item';
    item.textContent = `T${s.offset_s >= 0 ? '+' : ''}${s.offset_s}s  [${s.role}]  ${s.action}`;
    list.appendChild(item);
  }
}

function createStrikePlan() {
  if (_pendingSteps.length === 0) return;
  _send('tactical.create_strike_plan', {
    steps: _pendingSteps.map(s => ({ role: s.role, action: s.action, offset_s: s.offset_s })),
  });
  _pendingSteps = [];
  renderPendingSteps();
}

// ---------------------------------------------------------------------------
// Canvas interaction
// ---------------------------------------------------------------------------

function handleCanvasClick(relX, relY) {
  if (!_tacState || !_shipState || !_send) return;

  const sx    = _shipState.position?.x || 50_000;
  const sy    = _shipState.position?.y || 50_000;
  const w     = canvas.width;
  const h     = canvas.height;
  const scale = Math.min(w, h) / 2 / MAP_WORLD_RADIUS;

  const wx = sx + (relX - w / 2) / scale;
  const wy = sy + (relY - h / 2) / scale;

  if (_activeTool === 'waypoint') {
    _send('tactical.add_annotation', { annotation_type: 'waypoint', x: wx, y: wy, label: 'WPT', text: '' });
    setTool(null);
    return;
  }

  if (_activeTool === 'note') {
    const text = window.prompt('Enter note text:');
    if (text) {
      _send('tactical.add_annotation', { annotation_type: 'note', x: wx, y: wy, label: text, text });
    }
    setTool(null);
    return;
  }

  // No tool active: click nearest enemy to toggle intercept target
  const threshold = MAP_WORLD_RADIUS * 0.06;
  let nearest     = null;
  let nearestDist = Infinity;
  for (const e of (_tacState?.enemies || [])) {
    const d = Math.hypot(e.x - wx, e.y - wy);
    if (d < nearestDist && d < threshold) {
      nearestDist = d;
      nearest     = e;
    }
  }
  if (nearest) {
    const newTarget = (nearest.id === _tacState.intercept_target_id) ? null : nearest.id;
    _send('tactical.set_intercept_target', { entity_id: newTarget });
  }
}

// ---------------------------------------------------------------------------
// Canvas rendering
// ---------------------------------------------------------------------------

function resizeCanvas() {
  const wrap = canvas.parentElement;
  const w    = wrap.clientWidth;
  const h    = wrap.clientHeight;
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

  if (!_tacState || !_shipState) {
    ctx.fillStyle = '#336633';
    ctx.font      = '12px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('AWAITING DATA', w / 2, h / 2);
    return;
  }

  const ship  = _shipState;
  const sx    = ship.position?.x || 50_000;
  const sy    = ship.position?.y || 50_000;
  const scale = Math.min(w, h) / 2 / MAP_WORLD_RADIUS;

  // Background grid rings
  ctx.strokeStyle = '#1a2a1a';
  ctx.lineWidth   = 1;
  for (const r of [10_000, 20_000, 30_000, 40_000, 50_000]) {
    ctx.beginPath();
    ctx.arc(w / 2, h / 2, r * scale, 0, Math.PI * 2);
    ctx.stroke();
  }

  // Intercept line (dashed blue)
  const iTarget = _tacState.intercept_target_id;
  if (iTarget) {
    const enemy = (_tacState.enemies || []).find(e => e.id === iTarget);
    if (enemy) {
      const ex = w / 2 + (enemy.x - sx) * scale;
      const ey = h / 2 + (enemy.y - sy) * scale;
      ctx.strokeStyle = 'rgba(128,192,255,0.5)';
      ctx.lineWidth   = 1.5;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(w / 2, h / 2);
      ctx.lineTo(ex, ey);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // Annotations
  for (const a of (_tacState.annotations || [])) {
    const ax = w / 2 + (a.x - sx) * scale;
    const ay = h / 2 + (a.y - sy) * scale;
    ctx.fillStyle   = '#f0c040';
    ctx.strokeStyle = '#f0c040';
    ctx.lineWidth   = 1.5;
    ctx.beginPath();
    ctx.arc(ax, ay, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.font      = '9px monospace';
    ctx.textAlign = 'center';
    ctx.fillText((a.label || a.type).toUpperCase(), ax, ay - 8);
  }

  // Enemy contacts
  for (const e of (_tacState.enemies || [])) {
    const ex = w / 2 + (e.x - sx) * scale;
    const ey = h / 2 + (e.y - sy) * scale;

    const threat   = e.threat_level || 'low';
    const colour   = THREAT_COLOURS[threat] || THREAT_COLOURS.low;
    const priority = e.engagement_priority;

    // Engagement priority ring
    if (priority === 'primary') {
      ctx.strokeStyle = colour;
      ctx.lineWidth   = 2;
      ctx.beginPath();
      ctx.arc(ex, ey, 14, 0, Math.PI * 2);
      ctx.stroke();
    } else if (priority === 'secondary') {
      ctx.strokeStyle = '#80c0ff';
      ctx.lineWidth   = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.arc(ex, ey, 14, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
    } else if (priority === 'ignore') {
      ctx.strokeStyle = '#555';
      ctx.lineWidth   = 1;
      ctx.beginPath();
      ctx.arc(ex, ey, 14, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Triangle enemy marker
    const s = 7;
    ctx.fillStyle = colour;
    ctx.beginPath();
    ctx.moveTo(ex,     ey - s);
    ctx.lineTo(ex + s, ey + s);
    ctx.lineTo(ex - s, ey + s);
    ctx.closePath();
    ctx.fill();

    // Label + threat initial
    ctx.fillStyle = colour;
    ctx.font      = '10px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(e.id.toUpperCase(), ex, ey + s + 13);
    ctx.font = '8px monospace';
    ctx.fillText(`[${threat[0].toUpperCase()}]`, ex, ey + s + 22);
  }

  // Player ship (green dot + ring)
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

  // Active tool hint
  if (_activeTool) {
    ctx.fillStyle = 'rgba(240,192,64,0.8)';
    ctx.font      = '11px monospace';
    ctx.textAlign = 'left';
    ctx.fillText(`MODE: ${_activeTool.toUpperCase()} \u2014 Click to place`, 10, h - 10);
  }
}
