/**
 * ship_status.js — Ship status silhouette panel + system controls.
 *
 * Two panels:
 *   1. Ship silhouette canvas — top-down view coloured by system health.
 *      Click a system zone to see a detail popover.
 *      Toggle: Systems view | Crew view.
 *
 *   2. System controls table — per-system on/off toggle (Captain override),
 *      power %, health %, efficiency.
 */

// System definitions (draw order = visual layering on silhouette)
const SYSTEM_ZONES = [
  // { key, label, zone: [cx%, cy%, rx%, ry%] as % of canvas size }
  // (drawn as rounded rectangles on a top-down ship silhouette)
  { key: 'beams',        label: 'BEAMS',     zone: [50, 18, 22, 8] },
  { key: 'torpedoes',    label: 'TORPS',     zone: [50, 30, 14, 6] },
  { key: 'sensors',      label: 'SENSORS',   zone: [50, 43, 18, 7] },
  { key: 'manoeuvring',  label: 'MANOEUVRE', zone: [50, 55, 16, 7] },
  { key: 'shields',      label: 'SHIELDS',   zone: [50, 50, 38, 18] },  // big oval
  { key: 'engines',      label: 'ENGINES',   zone: [50, 74, 20, 9] },
  { key: 'flight_deck',  label: 'FLT DECK',  zone: [50, 85, 24, 7] },
  { key: 'point_defence',label: 'POINT DEF', zone: [30, 60, 10, 6] },
  { key: 'ecm_suite',    label: 'ECM',       zone: [70, 60, 10, 6] },
];

const CREW_DECKS = [
  { key: 'bridge',     label: 'BRIDGE',   zone: [50, 20, 24, 8] },
  { key: 'ops',        label: 'OPS',      zone: [50, 32, 22, 8] },
  { key: 'engineering',label: 'ENGRNG',   zone: [50, 44, 22, 8] },
  { key: 'medical',    label: 'MEDICAL',  zone: [50, 56, 22, 8] },
  { key: 'security',   label: 'SECURITY', zone: [50, 68, 22, 8] },
  { key: 'flight',     label: 'FLIGHT',   zone: [50, 80, 22, 8] },
];

let _canvas, _ctx;
let _systemsState = {};
let _crewState = {};
let _overridesState = {};
let _mode = 'systems';  // 'systems' | 'crew'
let _popover = null;
let _onOverrideToggle = null;
let _controlRows = {};  // { system_key: { row, status, pwr, health, eff } }
let _sendFn = null;
let _systemControlsPanel = null;
let _crewMgmtPanel = null;
let _crewMgmtList = null;
let _rosterData = [];   // Array of crew member dicts from crew.roster

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

/**
 * @param {HTMLCanvasElement} canvas
 * @param {HTMLElement} controlsContainer — where to build the system controls table
 * @param {HTMLElement} toggleBtn — toggle Systems/Crew button
 * @param {Function} onOverrideToggle(system, online) — called when Captain toggles
 * @param {Function} [sendFn] — WebSocket send function for crew reassignment
 */
export function initShipStatus(canvas, controlsContainer, toggleBtn, onOverrideToggle, sendFn) {
  _canvas = canvas;
  _ctx = canvas.getContext('2d');
  _onOverrideToggle = onOverrideToggle;
  _sendFn = sendFn || null;

  _systemControlsPanel = document.getElementById('system-controls-panel');
  _crewMgmtPanel = document.getElementById('crew-mgmt-panel');
  _crewMgmtList = document.getElementById('crew-mgmt-list');

  _sizeCanvas();
  window.addEventListener('resize', _sizeCanvas);

  canvas.addEventListener('click', _onCanvasClick);

  toggleBtn.addEventListener('click', () => {
    _mode = _mode === 'systems' ? 'crew' : 'systems';
    toggleBtn.textContent = _mode === 'systems' ? 'CREW VIEW' : 'SYSTEMS VIEW';
    _updatePanelVisibility();
    _draw();
  });

  _buildSystemControls(controlsContainer);
  _updatePanelVisibility();
  _draw();
}

function _updatePanelVisibility() {
  if (_systemControlsPanel) _systemControlsPanel.style.display = _mode === 'systems' ? '' : 'none';
  if (_crewMgmtPanel) _crewMgmtPanel.style.display = _mode === 'crew' ? '' : 'none';
}

function _sizeCanvas() {
  if (!_canvas) return;
  const rect = _canvas.parentElement?.getBoundingClientRect();
  if (rect) {
    _canvas.width  = rect.width  || 220;
    _canvas.height = rect.width  || 220;  // square
  }
  _draw();
}

// ---------------------------------------------------------------------------
// State updates
// ---------------------------------------------------------------------------

export function updateSystems(systemsPayload) {
  _systemsState = systemsPayload || {};
  _draw();
  _updateControlRows();
}

export function updateCrew(crewPayload) {
  _crewState = crewPayload || {};
  _draw();
}

export function updateRoster(roster) {
  _rosterData = roster || [];
  if (_mode === 'crew') _buildCrewMgmtList();
}

export function updateOverrides(overridesPayload) {
  _overridesState = overridesPayload || {};
  _draw();
  _updateControlOverrideUI();
}

// ---------------------------------------------------------------------------
// Silhouette drawing
// ---------------------------------------------------------------------------

function _draw() {
  if (!_canvas || !_ctx) return;
  const W = _canvas.width;
  const H = _canvas.height;
  const ctx = _ctx;

  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#050a12';
  ctx.fillRect(0, 0, W, H);

  // Draw ship outline (simple torpedo shape)
  _drawShipOutline(ctx, W, H);

  if (_mode === 'systems') {
    for (const zone of SYSTEM_ZONES) {
      _drawZone(ctx, W, H, zone, _systemsState[zone.key]);
    }
  } else {
    for (const deck of CREW_DECKS) {
      _drawCrewZone(ctx, W, H, deck, _crewState[deck.key]);
    }
  }
}

function _drawShipOutline(ctx, W, H) {
  ctx.save();
  ctx.strokeStyle = 'rgba(0,170,255,0.3)';
  ctx.lineWidth = 1;
  // Simple elongated ship silhouette
  ctx.beginPath();
  ctx.ellipse(W/2, H/2, W*0.28, H*0.47, 0, 0, Math.PI*2);
  ctx.stroke();
  // Nose point
  ctx.beginPath();
  ctx.moveTo(W*0.35, H*0.12);
  ctx.lineTo(W*0.5, H*0.06);
  ctx.lineTo(W*0.65, H*0.12);
  ctx.stroke();
  // Aft notch
  ctx.beginPath();
  ctx.moveTo(W*0.35, H*0.88);
  ctx.lineTo(W*0.5, H*0.94);
  ctx.lineTo(W*0.65, H*0.88);
  ctx.stroke();
  ctx.restore();
}

function _drawZone(ctx, W, H, zone, sys) {
  const [cx, cy, rx, ry] = zone.zone;
  const x  = W * cx/100;
  const y  = H * cy/100;
  const rw = W * rx/100;
  const rh = H * ry/100;

  const health = sys?.health ?? 100;
  const color  = _healthColor(health);

  ctx.save();
  ctx.globalAlpha = 0.7;
  ctx.fillStyle   = color + '33';
  ctx.strokeStyle = color;
  ctx.lineWidth   = 1;

  ctx.beginPath();
  _rrect(ctx, x - rw, y - rh, rw * 2, rh * 2, 4);
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle    = color;
  ctx.font         = `bold ${Math.max(10, rh * 0.8)}px "Courier New"`;
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'middle';
  ctx.globalAlpha  = 1;
  ctx.fillText(zone.label, x, y);
  ctx.restore();

  // Override hatching
  if (_overridesState[zone.key] === false) {
    ctx.save();
    ctx.strokeStyle = '#ff2020';
    ctx.lineWidth   = 1;
    ctx.globalAlpha = 0.6;
    ctx.setLineDash([3, 3]);
    for (let i = -rw; i < rw; i += 6) {
      ctx.beginPath();
      ctx.moveTo(x + i - rh, y - rh);
      ctx.lineTo(x + i + rh, y + rh);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
    ctx.fillStyle = '#ff2020';
    ctx.font = `bold ${Math.max(10, rh * 0.7)}px "Courier New"`;
    ctx.textAlign = 'center';
    ctx.fillText('OVERRIDE', x, y + rh * 0.5);
    ctx.restore();
  }
}

function _drawCrewZone(ctx, W, H, deck, crew) {
  const [cx, cy, rx, ry] = deck.zone;
  const x  = W * cx/100;
  const y  = H * cy/100;
  const rw = W * rx/100;
  const rh = H * ry/100;

  const total  = crew?.total  ?? 0;
  const active = crew?.active ?? 0;
  const dead   = crew?.dead   ?? 0;
  const pct    = total > 0 ? active / total : 1;
  const color  = dead > 0 ? '#ff2020' : (pct < 0.5 ? '#ffb000' : '#00ff41');

  ctx.save();
  ctx.globalAlpha = 0.7;
  ctx.fillStyle   = color + '33';
  ctx.strokeStyle = color;
  ctx.lineWidth   = 1;
  ctx.beginPath();
  _rrect(ctx, x - rw, y - rh, rw * 2, rh * 2, 4);
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle    = color;
  ctx.font         = `${Math.max(10, rh * 0.75)}px "Courier New"`;
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'middle';
  ctx.globalAlpha  = 1;
  ctx.fillText(`${deck.label} ${active}/${total}`, x, y);
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Click hit-test → popover
// ---------------------------------------------------------------------------

function _onCanvasClick(e) {
  const rect = _canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const W  = _canvas.width;
  const H  = _canvas.height;

  const zones = _mode === 'systems' ? SYSTEM_ZONES : CREW_DECKS;
  for (const zone of zones) {
    const [cx, cy, rx, ry] = zone.zone;
    const x  = W * cx/100;
    const y  = H * cy/100;
    const rw = W * rx/100;
    const rh = H * ry/100;
    if (mx >= x - rw && mx <= x + rw && my >= y - rh && my <= y + rh) {
      _showPopover(zone, mx, my, e.target.parentElement);
      return;
    }
  }
  _hidePopover();
}

function _showPopover(zone, mx, my, container) {
  _hidePopover();

  const el = document.createElement('div');
  el.className = 'status-popover';

  if (_mode === 'systems') {
    const sys = _systemsState[zone.key] || {};
    const online = _overridesState[zone.key] !== false;
    el.innerHTML = `
      <div class="popover-title">${zone.label}</div>
      <div class="popover-row"><span>Health</span><span class="${_healthClass(sys.health || 0)}">${Math.round(sys.health || 0)}%</span></div>
      <div class="popover-row"><span>Power</span><span>${Math.round(sys.power || 0)}%</span></div>
      <div class="popover-row"><span>Efficiency</span><span>${(sys.efficiency || 0).toFixed(2)}</span></div>
      <div class="popover-row"><span>Override</span><span class="${online ? 'pop-online' : 'pop-offline'}">${online ? 'ONLINE' : 'OFFLINE'}</span></div>
    `;
  } else {
    const crew = _crewState[zone.key] || {};
    el.innerHTML = `
      <div class="popover-title">${zone.label}</div>
      <div class="popover-row"><span>Active</span><span>${crew.active || 0}</span></div>
      <div class="popover-row"><span>Injured</span><span>${crew.injured || 0}</span></div>
      <div class="popover-row"><span>Critical</span><span>${crew.critical || 0}</span></div>
      <div class="popover-row"><span>Dead</span><span>${crew.dead || 0}</span></div>
      <div class="popover-row"><span>Factor</span><span>${(crew.crew_factor || 1).toFixed(2)}</span></div>
    `;
  }

  el.style.cssText = `
    position:absolute; left:${Math.min(mx+8, 200)}px; top:${my}px;
    background:#0a1520; border:1px solid #00aaff; padding:8px; z-index:50;
    font-family:'Courier New',monospace; font-size:11px; color:#e8f4f8;
    pointer-events:none; white-space:nowrap;
  `;
  container.appendChild(el);
  _popover = el;

  setTimeout(_hidePopover, 3000);
}

function _hidePopover() {
  if (_popover) { _popover.remove(); _popover = null; }
}

// ---------------------------------------------------------------------------
// System controls table
// ---------------------------------------------------------------------------

const SYSTEM_DEFS = [
  { key: 'engines',      label: 'Engines' },
  { key: 'beams',        label: 'Beams' },
  { key: 'torpedoes',    label: 'Torpedoes' },
  { key: 'shields',      label: 'Shields' },
  { key: 'sensors',      label: 'Sensors' },
  { key: 'manoeuvring',  label: 'Manoeuvring' },
  { key: 'flight_deck',  label: 'Flight Deck' },
  { key: 'ecm_suite',    label: 'ECM Suite' },
  { key: 'point_defence',label: 'Point Defence' },
];

function _buildSystemControls(container) {
  container.innerHTML = '';

  for (const def of SYSTEM_DEFS) {
    const row = document.createElement('div');
    row.className = 'sys-ctrl-row';

    // Toggle button
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'sys-ctrl-toggle sys-ctrl-toggle--on';
    toggleBtn.textContent = 'ON';
    toggleBtn.title = `Captain: take ${def.label} offline`;

    toggleBtn.addEventListener('click', () => {
      const currentlyOnline = !(_overridesState[def.key] === false);
      const newOnline = !currentlyOnline;
      if (!newOnline && !confirm(`Take ${def.label.toUpperCase()} offline?\nEngineering will lose control.`)) return;
      if (_onOverrideToggle) _onOverrideToggle(def.key, newOnline);
    });

    // System name
    const nameEl = document.createElement('span');
    nameEl.className = 'sys-ctrl-name';
    nameEl.textContent = def.label;

    // Power
    const pwrEl = document.createElement('span');
    pwrEl.className = 'sys-ctrl-pwr';
    pwrEl.textContent = '—%';

    // Health bar
    const healthWrap = document.createElement('div');
    healthWrap.className = 'sys-ctrl-health-wrap';
    const healthBar = document.createElement('div');
    healthBar.className = 'sys-ctrl-health-bar';
    healthWrap.appendChild(healthBar);

    // Efficiency
    const effEl = document.createElement('span');
    effEl.className = 'sys-ctrl-eff';
    effEl.textContent = '—';

    row.appendChild(toggleBtn);
    row.appendChild(nameEl);
    row.appendChild(pwrEl);
    row.appendChild(healthWrap);
    row.appendChild(effEl);
    container.appendChild(row);

    _controlRows[def.key] = { row, toggleBtn, pwrEl, healthBar, effEl };
  }
}

function _updateControlRows() {
  for (const def of SYSTEM_DEFS) {
    const els = _controlRows[def.key];
    const sys = _systemsState[def.key];
    if (!els || !sys) continue;

    els.pwrEl.textContent = `${Math.round(sys.power)}%`;
    els.healthBar.style.width = `${Math.max(0, sys.health)}%`;
    els.healthBar.style.background = _healthColor(sys.health);
    els.effEl.textContent = sys.efficiency.toFixed(2);
  }
}

function _updateControlOverrideUI() {
  for (const def of SYSTEM_DEFS) {
    const els = _controlRows[def.key];
    if (!els) continue;
    const online = _overridesState[def.key] !== false;
    els.toggleBtn.textContent = online ? 'ON' : 'OFF';
    els.toggleBtn.className = `sys-ctrl-toggle ${online ? 'sys-ctrl-toggle--on' : 'sys-ctrl-toggle--off'}`;
    els.row.classList.toggle('sys-ctrl-row--override', !online);
    _draw();
  }
}

// ---------------------------------------------------------------------------
// Crew management list
// ---------------------------------------------------------------------------

const DUTY_STATIONS = [
  'manoeuvring', 'sensors', 'beams', 'torpedoes', 'shields', 'medical_bay', 'engines',
];

const DUTY_STATION_LABELS = {
  manoeuvring: 'Bridge',
  sensors:     'Sensors',
  beams:       'Beams',
  torpedoes:   'Torpedoes',
  shields:     'Shields',
  medical_bay: 'Medical',
  engines:     'Engines',
};

function _buildCrewMgmtList() {
  if (!_crewMgmtList) return;
  _crewMgmtList.innerHTML = '';

  // Only show active/injured crew that can be reassigned
  const eligible = _rosterData.filter(m =>
    m.status !== 'dead' &&
    !['medical_bay', 'quarantine', 'morgue'].includes(m.location)
  );

  if (!eligible.length) {
    _crewMgmtList.innerHTML = '<div class="text-dim" style="padding:.4rem .6rem;font-size:.75rem">No crew available for reassignment.</div>';
    return;
  }

  // Group by current duty station
  const byStation = {};
  for (const m of eligible) {
    const st = m.duty_station;
    if (!byStation[st]) byStation[st] = [];
    byStation[st].push(m);
  }

  for (const station of DUTY_STATIONS) {
    const crew = byStation[station];
    if (!crew || !crew.length) continue;

    const header = document.createElement('div');
    header.className = 'crew-mgmt-station-header';
    header.textContent = (DUTY_STATION_LABELS[station] || station).toUpperCase();
    _crewMgmtList.appendChild(header);

    for (const m of crew) {
      const row = document.createElement('div');
      row.className = 'crew-mgmt-row';
      if (m.reassignment_timer > 0) row.classList.add('crew-mgmt-row--transitioning');

      // Name + status
      const nameEl = document.createElement('span');
      nameEl.className = 'crew-mgmt-name';
      const statusMark = m.status === 'active' ? '' : ` [${m.status.toUpperCase()}]`;
      nameEl.textContent = `${m.rank} ${m.surname}${statusMark}`;
      if (m.original_duty_station) {
        nameEl.title = `Reassigned from ${DUTY_STATION_LABELS[m.original_duty_station] || m.original_duty_station} (${m.reassignment_count}/2)`;
      }

      // Timer or select
      const actionEl = document.createElement('span');
      actionEl.className = 'crew-mgmt-action';

      if (m.reassignment_timer > 0) {
        actionEl.textContent = `${Math.ceil(m.reassignment_timer)}s`;
        actionEl.classList.add('crew-mgmt-timer');
      } else if (m.reassignment_count >= 2) {
        actionEl.textContent = 'MAX';
        actionEl.classList.add('crew-mgmt-maxed');
      } else {
        const select = document.createElement('select');
        select.className = 'crew-mgmt-select';
        const defaultOpt = document.createElement('option');
        defaultOpt.value = '';
        defaultOpt.textContent = '—';
        select.appendChild(defaultOpt);

        for (const ds of DUTY_STATIONS) {
          if (ds === m.duty_station) continue;
          const opt = document.createElement('option');
          opt.value = ds;
          opt.textContent = DUTY_STATION_LABELS[ds] || ds;
          select.appendChild(opt);
        }

        select.addEventListener('change', () => {
          if (select.value && _sendFn) {
            _sendFn('captain.reassign_crew', { crew_id: m.id, new_duty_station: select.value });
          }
          select.value = '';
        });

        actionEl.appendChild(select);
      }

      row.appendChild(nameEl);
      row.appendChild(actionEl);
      _crewMgmtList.appendChild(row);
    }
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _healthColor(health) {
  if (health > 60) return '#00ff41';
  if (health > 30) return '#ffb000';
  return '#ff2020';
}

function _healthClass(health) {
  if (health > 60) return 'pop-green';
  if (health > 30) return 'pop-amber';
  return 'pop-red';
}

function _rrect(ctx, x, y, w, h, r) {
  r = Math.min(r, w/2, h/2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y,     x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x,     y + h, x,         y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x,     y,     x + r,     y);
  ctx.closePath();
}
