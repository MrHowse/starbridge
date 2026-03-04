/**
 * Starbridge — Operations Station (v0.08)
 *
 * The crew's analyst and coordinator. Processes raw data from Science and
 * other stations into tactical intelligence, and pushes concrete, measurable
 * bonuses to Weapons, Helm, Flight Ops, and other stations.
 *
 * Replaces the old Tactical Officer station.
 *
 * Server messages received:
 *   operations.state    — full ops state (assessments, coordination, missions, feed)
 *   operations.event    — point events (assessment_complete, sync, evasion, etc.)
 *   sensor.contacts     — contacts + torpedoes for tactical map
 *   ship.state          — hull/shields/speed for bottom bar
 *   ship.alert_changed  — alert level colour change
 *
 * Server messages sent:
 *   operations.start_assessment   { contact_id }
 *   operations.cancel_assessment  {}
 *   operations.set_threat_level   { contact_id, level }
 *   operations.set_vulnerable_facing  { contact_id, facing }
 *   operations.set_priority_subsystem { contact_id, subsystem }
 *   operations.toggle_prediction  { contact_id, active }
 *   operations.set_weapons_helm_sync  { contact_id }
 *   operations.cancel_weapons_helm_sync {}
 *   operations.set_sensor_focus   { center_x, center_y, radius }
 *   operations.cancel_sensor_focus {}
 *   operations.start_damage_coordination {}
 *   operations.issue_evasion_alert { bearing }
 *   operations.mark_objective     { objective_id }
 *   operations.station_advisory   { target_station, message }
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import { setStatusDot, setAlertLevel } from '../shared/ui_components.js';
import { MapRenderer } from '../shared/map_renderer.js';
import { RangeControl, STATION_RANGES } from '../shared/range_control.js';
import { SoundBank } from '../shared/audio.js';
import '../shared/audio_events.js';
import '../shared/audio_ops.js';
import { wireButtonSounds } from '../shared/audio_ui.js';
import { registerHelp, initHelpOverlay } from '../shared/help_overlay.js';
import { initNotifications } from '../shared/notifications.js';
import { initRoleBar } from '../shared/role_bar.js';
import { initCrewRoster } from '../shared/crew_roster.js';

registerHelp([
  { selector: '#ops-canvas',          text: 'Tactical map — click contact to assess.', position: 'right' },
  { selector: '#ops-analysis',        text: 'Analysis — selected contact data and coordination bonuses.', position: 'right' },
  { selector: '#ops-feed-list',       text: 'Feed — real-time events from all stations.', position: 'left' },
  { selector: '#ops-mission-tracker', text: 'Mission tracker — click objectives to mark.', position: 'left' },
  { selector: '#ops-advisory-send',   text: 'Send advisory to a specific station.', position: 'above' },
]);

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const THREAT_COLORS = {
  low:      '#00ff41',
  medium:   '#ffaa00',
  high:     '#ff8800',
  critical: '#ff4040',
};

const CONTACT_COLORS = {
  hostile:  '#ff4040',
  unknown:  '#ffffff',
  friendly: '#00ff41',
  neutral:  '#ffaa00',
};

const STATUS_ICONS = {
  pending:   '\u25cb',  // ○
  active:    '\u25cf',  // ●
  complete:  '\u2713',  // ✓
  failed:    '\u2717',  // ✗
  cancelled: '\u2014',  // —
};

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusDotEl      = document.querySelector('[data-status-dot]');
const missionLabelEl   = document.querySelector('[data-mission-label]');
const standbyEl        = document.getElementById('ops-standby');
const mainEl           = document.getElementById('ops-main');
const feedListEl       = document.getElementById('ops-feed-list');
const hullStatusEl     = document.getElementById('ops-hull-status');
const shieldStatusEl   = document.getElementById('ops-shield-status');
const speedStatusEl    = document.getElementById('ops-speed-status');
const analysisEl       = document.getElementById('ops-analysis-content');
const coordinationEl   = document.getElementById('ops-coordination-content');
const missionTrackerEl = document.getElementById('ops-mission-tracker');
const coordSummaryEl   = document.getElementById('ops-coord-summary');
const assessQueueEl    = document.getElementById('ops-assessment-queue');
const canvasEl         = document.getElementById('ops-canvas');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _gameActive = false;
let _opsState   = null;
let _contacts   = [];
let _torpedoes  = [];
let _shipState  = null;
let _selectedId = null;
let _mapRenderer  = null;
let _rangeControl = null;
let _rafId = null;
let _flagBridgeState = null;

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  onStatusChange((status) => {
    setStatusDot(statusDotEl, status === 'connected' ? 'connected' : 'disconnected');
    if (status === 'connected') {
      const name = sessionStorage.getItem('player_name') || 'OPERATIONS';
      send('lobby.claim_role', { role: 'operations', player_name: name });
    }
  });

  on('game.started',       handleGameStarted);
  on('game.over',          handleGameOver);
  on('ship.state',         handleShipState);
  on('ship.alert_changed', ({ level }) => setAlertLevel(level));
  on('operations.state',   handleOpsState);
  on('operations.event',   handleOpsEvent);
  on('sensor.contacts',    handleSensorContacts);
  on('flag_bridge.state',  (p) => { _flagBridgeState = p; });

  setupAdvisory();
  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();
  initNotifications(send, 'operations');
  initRoleBar(send, 'operations');
  initCrewRoster(send);
  connect();
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function handleGameStarted(payload) {
  _gameActive = true;
  standbyEl.classList.add('ops-standby--hidden');
  mainEl.style.display = '';
  if (payload.mission_name) {
    missionLabelEl.textContent = payload.mission_name.toUpperCase();
  }

  // Set up range control.
  const opsRanges = STATION_RANGES.operations;
  _rangeControl = new RangeControl({
    container: document.getElementById('ops-range-bar'),
    stationId: 'operations',
    ranges: opsRanges.available,
    defaultRange: opsRanges.default,
    onChange: (_key, worldUnits) => {
      if (_mapRenderer) _mapRenderer.setRange(worldUnits);
    },
  });
  _rangeControl.attach();

  // Set up map renderer.
  requestAnimationFrame(() => {
    _mapRenderer = new MapRenderer(canvasEl, {
      range: _rangeControl.currentRangeUnits(),
      orientation: 'north-up',
      showGrid: true,
      showRangeRings: true,
      interactive: true,
      zoom: { enabled: true },
      drawContact: drawOpsContact,
    });
    const sc = payload.ship_class || '';
    if (sc) _mapRenderer.loadShipSilhouette(sc);
    _mapRenderer.onContactClick(handleContactClick);
    renderLoop();
  });
}

function handleGameOver(payload) {
  _gameActive = false;
  standbyEl.classList.remove('ops-standby--hidden');
  mainEl.style.display = 'none';
  if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null; }
}

function handleShipState(payload) {
  if (!_gameActive) return;
  _shipState = payload;
  if (_mapRenderer) _mapRenderer.updateShipState(payload);
  updateShipStatus(payload);
}

function handleOpsState(payload) {
  if (!_gameActive) return;
  _opsState = payload;

  // Process feed events.
  if (payload.feed_events) {
    for (const evt of payload.feed_events) {
      addFeedEvent(evt.source, evt.text, evt.severity);
    }
  }

  updateAnalysisPanel();
  updateCoordinationPanel();
  updateMissionTracker();
  updateBottomBar();
}

function handleOpsEvent(payload) {
  const type = payload.type;
  switch (type) {
    case 'assessment_complete':
      SoundBank.play('ops_assessment_complete');
      break;
    case 'weapons_helm_sync':
      SoundBank.play('ops_sync_activated');
      break;
    case 'sensor_focus':
      break;
    case 'sensor_focus_cancelled':
      SoundBank.play('ops_sync_broken');
      break;
    case 'threat_level':
      if (payload.level === 'critical') SoundBank.play('ops_threat_critical');
      break;
    case 'evasion_alert':
      SoundBank.play('ops_incoming_torpedo');
      break;
    case 'objective_marked':
      SoundBank.play('ops_mission_complete');
      break;
    case 'station_advisory':
      SoundBank.play('ops_advisory_sent');
      break;
    case 'damage_coordination_complete':
      SoundBank.play('ops_assessment_complete');
      break;
  }
}

function handleSensorContacts(payload) {
  if (!_gameActive) return;
  _contacts = payload.contacts || [];
  _torpedoes = payload.torpedoes || [];
  if (_mapRenderer) {
    _mapRenderer.updateContacts(_contacts, _torpedoes);
  }
}

// ---------------------------------------------------------------------------
// Render loop
// ---------------------------------------------------------------------------

function renderLoop() {
  if (!_gameActive || !_mapRenderer) return;
  const now = performance.now();
  _mapRenderer.render(now);

  // Post-render overlays.
  if (_opsState) {
    const ctx = canvasEl.getContext('2d');
    drawCoordinationOverlays(ctx, now);
  }

  _rafId = requestAnimationFrame(renderLoop);
}

// ---------------------------------------------------------------------------
// Tactical map — custom contact renderer (A.5.1.2)
// ---------------------------------------------------------------------------

function drawOpsContact(ctx, sx, sy, contact, selected, now) {
  const assessment = _opsState?.assessments?.[contact.id];
  const threatLevel = assessment?.threat_level || null;

  // Colour by threat level if assessed, else by classification.
  let color;
  if (threatLevel) {
    color = THREAT_COLORS[threatLevel] || '#ffffff';
  } else {
    const cls = contact.classification || 'hostile';
    if (cls === 'unknown') {
      const alpha = 0.5 + 0.5 * Math.sin(now * 0.004);
      color = `rgba(255,255,255,${alpha})`;
    } else {
      color = CONTACT_COLORS[cls] || CONTACT_COLORS.hostile;
    }
  }

  // Assessment progress ring (in-progress).
  if (assessment && !assessment.complete && assessment.progress > 0) {
    const progress = assessment.progress / 15.0;
    ctx.save();
    ctx.strokeStyle = 'rgba(0, 170, 255, 0.6)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(sx, sy, 16, -Math.PI / 2, -Math.PI / 2 + progress * Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  // Assessment complete indicator.
  if (assessment?.complete) {
    ctx.save();
    ctx.strokeStyle = 'rgba(0, 255, 65, 0.5)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(sx, sy, 16, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  // Base shape — diamond for enemies, circle for stations, triangle for creatures.
  ctx.save();
  ctx.fillStyle = color;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  const kind = contact.kind || 'enemy';
  if (kind === 'station') {
    ctx.beginPath();
    ctx.rect(sx - 5, sy - 5, 10, 10);
    ctx.stroke();
  } else if (kind === 'creature') {
    ctx.beginPath();
    ctx.moveTo(sx, sy - 7);
    ctx.lineTo(sx + 6, sy + 5);
    ctx.lineTo(sx - 6, sy + 5);
    ctx.closePath();
    ctx.stroke();
  } else {
    // Enemy — diamond.
    ctx.beginPath();
    ctx.moveTo(sx, sy - 7);
    ctx.lineTo(sx + 6, sy);
    ctx.lineTo(sx, sy + 7);
    ctx.lineTo(sx - 6, sy);
    ctx.closePath();
    ctx.fill();
  }
  ctx.restore();

  // Selected highlight.
  if (selected || contact.id === _selectedId) {
    ctx.save();
    ctx.strokeStyle = '#00aaff';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.arc(sx, sy, 20, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }

  // Prediction line (dashed).
  if (assessment?.prediction?.active && _mapRenderer) {
    const pred = assessment.prediction;
    const pp = _mapRenderer.worldToCanvas(pred.predicted_x, pred.predicted_y);
    const confColor = { high: '#00ff41', medium: '#ffaa00', low: '#ff4040' }[pred.confidence] || '#ff4040';
    ctx.save();
    ctx.strokeStyle = confColor;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.globalAlpha = 0.6;
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(pp.x, pp.y);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(pp.x, pp.y, 3, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }

  // Threat level label.
  if (threatLevel) {
    ctx.save();
    ctx.font = '11px monospace';
    ctx.fillStyle = THREAT_COLORS[threatLevel] || '#fff';
    ctx.textAlign = 'center';
    ctx.fillText(threatLevel.toUpperCase()[0], sx, sy - 20);
    ctx.restore();
  }
}

// ---------------------------------------------------------------------------
// Post-render coordination overlays
// ---------------------------------------------------------------------------

function drawCoordinationOverlays(ctx, now) {
  if (!_mapRenderer || !_opsState) return;
  const coord = _opsState.coordination_bonuses || {};

  // Sync vector line.
  if (coord.weapons_helm_sync?.active && coord.weapons_helm_sync.contact_id) {
    const target = _contacts.find(c => c.id === coord.weapons_helm_sync.contact_id);
    if (target) {
      const cw = canvasEl.width;
      const ch = canvasEl.height;
      const tp = _mapRenderer.worldToCanvas(target.x, target.y);
      ctx.save();
      ctx.strokeStyle = 'rgba(0, 200, 255, 0.4)';
      ctx.lineWidth = 1;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(cw / 2, ch / 2);
      ctx.lineTo(tp.x, tp.y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    }
  }

  // Sensor focus zone.
  if (coord.sensor_focus) {
    const sf = coord.sensor_focus;
    const cp = _mapRenderer.worldToCanvas(sf.center_x, sf.center_y);
    const edgeP = _mapRenderer.worldToCanvas(sf.center_x + sf.radius, sf.center_y);
    const rPx = Math.abs(edgeP.x - cp.x);
    ctx.save();
    ctx.strokeStyle = 'rgba(0, 255, 65, 0.25)';
    ctx.fillStyle = 'rgba(0, 255, 65, 0.04)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.arc(cp.x, cp.y, rPx, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }

  // Evasion alert bearing indicator.
  if (coord.evasion_alert) {
    const cw = canvasEl.width;
    const ch = canvasEl.height;
    const bearRad = (coord.evasion_alert.bearing - 90) * Math.PI / 180;
    const len = Math.min(cw, ch) * 0.35;
    ctx.save();
    ctx.strokeStyle = 'rgba(255, 68, 68, 0.6)';
    ctx.lineWidth = 2;
    ctx.setLineDash([8, 4]);
    ctx.beginPath();
    ctx.moveTo(cw / 2, ch / 2);
    ctx.lineTo(cw / 2 + Math.cos(bearRad) * len, ch / 2 + Math.sin(bearRad) * len);
    ctx.stroke();
    ctx.setLineDash([]);
    // Pulsing "EVADE" label.
    const alpha = 0.5 + 0.5 * Math.sin(now * 0.008);
    ctx.fillStyle = `rgba(255, 68, 68, ${alpha})`;
    ctx.font = 'bold 12px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('EVADE', cw / 2 + Math.cos(bearRad) * (len + 20), ch / 2 + Math.sin(bearRad) * (len + 20));
    ctx.restore();
  }
}

// ---------------------------------------------------------------------------
// Click handler
// ---------------------------------------------------------------------------

function handleContactClick(contactId) {
  if (contactId) {
    _selectedId = contactId;
    send('operations.start_assessment', { contact_id: contactId });
  }
}

// ---------------------------------------------------------------------------
// Analysis Panel (A.5.1.3)
// ---------------------------------------------------------------------------

function updateAnalysisPanel() {
  if (!analysisEl || !_opsState) return;

  if (!_selectedId || !_opsState.assessments[_selectedId]) {
    analysisEl.innerHTML = '<p class="text-dim">Select a contact to begin assessment.</p>';
    return;
  }

  const asmt = _opsState.assessments[_selectedId];
  const contact = _contacts.find(c => c.id === _selectedId);
  let html = '';

  // Contact header.
  html += `<div class="ops-contact-header">`;
  html += `<span class="text-bright">${_selectedId}</span>`;
  if (contact) html += ` <span class="text-dim">${contact.type || ''}</span>`;
  html += `</div>`;

  // Assessment status.
  if (asmt.complete) {
    html += `<div class="ops-assessed-badge">ASSESSED</div>`;
  } else {
    const pct = Math.round((asmt.progress / 15.0) * 100);
    html += `<div class="ops-progress"><div class="ops-progress-bar" style="width:${pct}%"></div></div>`;
    html += `<div class="text-dim">${pct}% complete</div>`;
  }

  // Threat level selector.
  html += `<div class="ops-threat-selector">`;
  for (const lvl of ['low', 'medium', 'high', 'critical']) {
    const active = asmt.threat_level === lvl ? ' ops-threat--active' : '';
    html += `<button class="ops-threat-btn ops-threat-btn--${lvl}${active}" `
         + `data-threat="${lvl}" data-contact="${_selectedId}">${lvl.toUpperCase()[0]}</button>`;
  }
  html += `</div>`;

  // Shield harmonics (if assessed).
  if (asmt.complete && asmt.shield_harmonics) {
    html += `<div class="ops-section-label">SHIELD HARMONICS</div>`;
    for (const facing of ['fore', 'aft', 'port', 'starboard']) {
      const val = asmt.shield_harmonics[facing] ?? 0;
      const isVuln = asmt.vulnerable_facing === facing;
      const cls = isVuln ? 'ops-bar--vuln' : '';
      html += `<div class="ops-bar-row">`;
      html += `<span class="ops-bar-label">${facing.toUpperCase().slice(0, 4)}</span>`;
      html += `<div class="ops-bar ${cls}"><div class="ops-bar-fill" style="width:${val}%"></div></div>`;
      html += `<span class="ops-bar-value">${Math.round(val)}%</span>`;
      html += `</div>`;
    }
  }

  // System health (if assessed).
  if (asmt.complete && asmt.system_health) {
    html += `<div class="ops-section-label">SYSTEM HEALTH</div>`;
    for (const [sys, hp] of Object.entries(asmt.system_health)) {
      const isPriority = asmt.priority_subsystem === sys;
      const cls = isPriority ? 'ops-bar--priority' : '';
      const barCls = hp < 25 ? 'ops-bar-fill--critical' : hp < 50 ? 'ops-bar-fill--warning' : '';
      html += `<div class="ops-bar-row">`;
      html += `<span class="ops-bar-label">${sys.slice(0, 6).toUpperCase()}</span>`;
      html += `<div class="ops-bar ${cls}"><div class="ops-bar-fill ${barCls}" style="width:${hp}%"></div></div>`;
      html += `<span class="ops-bar-value">${Math.round(hp)}%</span>`;
      html += `</div>`;
    }
  }

  // Prediction.
  if (asmt.prediction?.active) {
    const conf = asmt.prediction.confidence || 'low';
    html += `<div class="ops-section-label">PREDICTION: <span style="color:${
      conf === 'high' ? '#00ff41' : conf === 'medium' ? '#ffaa00' : '#ff4040'
    }">${conf.toUpperCase()}</span></div>`;
  }

  analysisEl.innerHTML = html;

  // Wire threat level buttons.
  analysisEl.querySelectorAll('.ops-threat-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      send('operations.set_threat_level', {
        contact_id: btn.dataset.contact,
        level: btn.dataset.threat,
      });
    });
  });
}

// ---------------------------------------------------------------------------
// Coordination Panel (A.5.1.3 lower)
// ---------------------------------------------------------------------------

function updateCoordinationPanel() {
  if (!coordinationEl || !_opsState) return;
  const coord = _opsState.coordination_bonuses || {};
  let html = '';

  // Weapons-Helm Sync.
  const sync = coord.weapons_helm_sync;
  if (sync) {
    const status = sync.active ? '<span class="text-good">ACTIVE</span>' : '<span class="text-dim">ALIGNING</span>';
    html += `<div class="ops-coord-item">SYNC: ${status} [${sync.contact_id}]</div>`;
  }

  // Sensor Focus.
  if (coord.sensor_focus) {
    html += `<div class="ops-coord-item">FOCUS: <span class="text-good">ACTIVE</span></div>`;
  }

  // Damage Coordination.
  const dc = coord.damage_coordination;
  if (dc) {
    if (dc.complete) {
      html += `<div class="ops-coord-item">DMG COORD: <span class="text-good">COMPLETE</span></div>`;
    } else {
      const pct = Math.round((dc.progress / 5.0) * 100);
      html += `<div class="ops-coord-item">DMG COORD: ${pct}%</div>`;
    }
  }

  // Evasion Alert.
  if (coord.evasion_alert) {
    html += `<div class="ops-coord-item ops-coord-item--critical">EVASION: ${Math.round(coord.evasion_alert.bearing)}\u00b0</div>`;
  }

  if (!html) {
    html = '<p class="text-dim">No active coordination bonuses.</p>';
  }
  coordinationEl.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Mission Tracker (A.5.1.4)
// ---------------------------------------------------------------------------

function updateMissionTracker() {
  if (!missionTrackerEl || !_opsState) return;
  const mt = _opsState.mission_tracking;
  if (!mt || !mt.title) {
    missionTrackerEl.innerHTML = '<p class="text-dim">No active missions.</p>';
    return;
  }

  let html = `<div class="ops-mission-title">${mt.title}</div>`;
  if (mt.objectives && mt.objectives.length > 0) {
    html += '<ul class="ops-obj-list">';
    for (const obj of mt.objectives) {
      const icon = STATUS_ICONS[obj.status] || '\u25cb';
      const marked = obj.ops_marked ? ' ops-obj--marked' : '';
      const station = obj.responsible_station ? ` <span class="ops-obj-station">[${obj.responsible_station}]</span>` : '';
      let eta = '';
      if (obj.status === 'active' && obj.estimated_time != null) {
        const s = Math.round(obj.estimated_time);
        const m = Math.floor(s / 60);
        const rem = s % 60;
        eta = ` <span class="ops-obj-eta">ETA: ${m}m ${String(rem).padStart(2, '0')}s</span>`;
      } else if (obj.status === 'active') {
        eta = ' <span class="ops-obj-eta">\u2014</span>';
      }
      html += `<li class="ops-obj${marked}" data-obj-id="${obj.id}">`;
      html += `<span class="ops-obj-icon">${icon}</span> ${obj.text}${station}${eta}`;
      html += `</li>`;
    }
    html += '</ul>';
  }
  missionTrackerEl.innerHTML = html;

  // Wire objective click to mark.
  missionTrackerEl.querySelectorAll('.ops-obj').forEach(el => {
    el.addEventListener('click', () => {
      send('operations.mark_objective', { objective_id: el.dataset.objId });
    });
  });
}

// ---------------------------------------------------------------------------
// Information Feed (A.5.2)
// ---------------------------------------------------------------------------

/**
 * Add an event to the information feed.
 * @param {string} source - Station tag (e.g., 'SCIENCE', 'WEAPONS')
 * @param {string} text - Event description
 * @param {'info'|'warning'|'critical'} severity
 */
function addFeedEvent(source, text, severity = 'info') {
  if (!feedListEl) return;
  const li = document.createElement('li');
  li.className = `ops-feed-item ops-feed-item--${severity} ops-feed-item--new`;
  const time = new Date().toLocaleTimeString('en-GB', { hour12: false });
  li.textContent = `[${time}] [${source}] ${text}`;
  feedListEl.appendChild(li);

  // Remove highlight class after animation.
  li.addEventListener('animationend', () => li.classList.remove('ops-feed-item--new'));

  // Cap at 50 items.
  while (feedListEl.children.length > 50) {
    feedListEl.removeChild(feedListEl.firstChild);
  }

  // Auto-scroll.
  feedListEl.scrollTop = feedListEl.scrollHeight;

  // Play audio for critical feed items.
  if (severity === 'critical') {
    SoundBank.play('ops_feed_critical');
  }
}

// ---------------------------------------------------------------------------
// Station Advisory (A.5.1.4 lower)
// ---------------------------------------------------------------------------

function setupAdvisory() {
  const input  = document.getElementById('ops-advisory-input');
  const target = document.getElementById('ops-advisory-target');
  const sendBtn = document.getElementById('ops-advisory-send');
  if (!input || !target || !sendBtn) return;

  sendBtn.addEventListener('click', () => {
    const msg = input.value.trim();
    const station = target.value;
    if (!msg || !station) return;
    send('operations.station_advisory', {
      target_station: station,
      message: msg,
    });
    input.value = '';
    target.selectedIndex = 0;
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendBtn.click();
  });
}

// ---------------------------------------------------------------------------
// Bottom bar (A.5.1.5)
// ---------------------------------------------------------------------------

function updateShipStatus(payload) {
  if (hullStatusEl) {
    hullStatusEl.textContent = `HULL ${Math.round(payload.hull || 0)}`;
  }
  if (shieldStatusEl) {
    const shields = payload.shields || {};
    const total = (shields.fore || 0) + (shields.aft || 0) +
                  (shields.port || 0) + (shields.starboard || 0);
    shieldStatusEl.textContent = `SHIELDS ${Math.round(total)}`;
  }
  if (speedStatusEl) {
    speedStatusEl.textContent = `SPD ${Math.round(payload.velocity || 0)}`;
  }
}

function updateBottomBar() {
  if (!_opsState) return;
  const coord = _opsState.coordination_bonuses || {};
  const asmt = _opsState.assessments || {};

  // Coordination summary.
  if (coordSummaryEl) {
    const parts = [];
    if (coord.weapons_helm_sync?.active) parts.push('SYNC');
    if (coord.sensor_focus) parts.push('FOCUS');
    if (coord.evasion_alert) parts.push('EVADE');
    if (coord.damage_coordination?.complete) parts.push('DMG');
    coordSummaryEl.textContent = parts.length ? parts.join(' | ') : '';
  }

  // Assessment queue.
  if (assessQueueEl) {
    const ids = Object.keys(asmt);
    const complete = ids.filter(id => asmt[id].complete).length;
    assessQueueEl.textContent = `ASSESS: ${complete}/${ids.length}`;
  }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
