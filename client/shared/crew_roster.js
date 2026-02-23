/**
 * Starbridge — Crew Roster Overlay
 *
 * Read-only personnel database accessible from any station via [CREW] button
 * or keyboard shortcut 'C'. Opens as a modal overlay — player stays on their
 * current station underneath.
 *
 * Receives crew data from:
 *   crew.roster    — full crew roster (broadcast to all roles)
 *   ship.state     — system power levels for effectiveness calculation
 *
 * Usage:
 *   import { initCrewRoster } from '../shared/crew_roster.js';
 *   initCrewRoster(send);
 */

import { on } from './connection.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DECK_NAMES = {
  1: 'BRIDGE',
  2: 'SENSORS',
  3: 'WEAPONS / SHIELDS',
  4: 'MEDICAL',
  5: 'ENGINEERING',
};

const DUTY_STATION_LABELS = {
  manoeuvring: 'Navigation',
  sensors:     'Sensors',
  beams:       'Beam Control',
  torpedoes:   'Torpedo Systems',
  shields:     'Life Support / Shields',
  engines:     'Drive Systems',
  medical_bay: 'Medical',
};

const STATUS_LABELS = {
  active:   'ACTIVE',
  injured:  'INJURED',
  critical: 'MEDICAL',
  dead:     'KIA',
};

const STATUS_CSS = {
  active:   'active',
  injured:  'injured',
  critical: 'medical',
  dead:     'kia',
};

const SEVERITY_ORDER = { critical: 0, serious: 1, moderate: 2, minor: 3 };

const SYSTEM_LABELS = {
  engines:       'Engines',
  beams:         'Beams',
  torpedoes:     'Torpedoes',
  shields:       'Shields',
  sensors:       'Sensors',
  manoeuvring:   'Manoeuvring',
  flight_deck:   'Flight Deck',
  ecm_suite:     'ECM',
  point_defence: 'Point Defence',
};

// Map system → duty station for crew factor calc
const SYSTEM_TO_DUTY = {
  engines:       'engines',
  beams:         'beams',
  torpedoes:     'torpedoes',
  shields:       'shields',
  sensors:       'sensors',
  manoeuvring:   'manoeuvring',
  flight_deck:   'manoeuvring',
  ecm_suite:     'sensors',
  point_defence: 'shields',
};

const FILTER_MODES = ['ALL', 'ACTIVE', 'INJURED', 'MEDICAL', 'KIA'];
const SORT_MODES   = ['RANK', 'DECK', 'NAME', 'STATUS'];

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _overlay     = null;
let _visible     = false;
let _initialised = false;
let _crewData    = {};        // crew_id → member dict
let _systemPower = {};        // system_name → power (0-150)
let _systemHealth = {};       // system_name → health (0-100)
let _shipName    = '';
let _shipClass   = '';
let _filter      = 'ALL';
let _sort        = 'DECK';
let _search      = '';
let _selectedId  = null;
let _expandedId  = null;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Initialise the crew roster overlay. Safe to call multiple times.
 * @param {function} send - WebSocket send helper (unused for read-only overlay)
 */
export function initCrewRoster(send) {
  if (_initialised) return;
  _initialised = true;

  _injectCSS();
  _buildOverlay();

  on('crew.roster', _handleCrewRoster);
  on('crew.roster_update', _handleRosterUpdate);
  on('ship.state', _handleShipState);
  on('game.started', _handleGameStarted);

  // Keyboard: C to toggle roster
  document.addEventListener('keydown', _handleKeydown);
}

/**
 * Programmatically toggle the roster overlay.
 */
export function toggleCrewRoster() {
  if (_visible) _hide();
  else _show();
}

// ---------------------------------------------------------------------------
// Overlay construction
// ---------------------------------------------------------------------------

function _buildOverlay() {
  _overlay = document.createElement('div');
  _overlay.className = 'crew-roster-overlay';
  _overlay.style.display = 'none';
  _overlay.setAttribute('role', 'dialog');
  _overlay.setAttribute('aria-label', 'Crew Manifest');

  // Click backdrop to close
  _overlay.addEventListener('click', (e) => {
    if (e.target === _overlay) _hide();
  });

  _overlay.innerHTML = `
    <div class="crew-roster">
      <div class="cr-header">
        <div class="cr-header__row1">
          <span class="cr-header__title" data-cr-title>CREW MANIFEST</span>
          <button class="cr-header__close" data-cr-close>✕ CLOSE</button>
        </div>
        <div class="cr-header__subtitle" data-cr-subtitle></div>
      </div>

      <div class="cr-readiness">
        <div class="cr-readiness__row">
          <span class="cr-readiness__label">SHIP READINESS:</span>
          <div class="cr-readiness__bar"><div class="cr-readiness__fill" data-cr-readiness-fill></div></div>
          <span class="cr-readiness__pct" data-cr-readiness-pct>—</span>
        </div>
        <div class="cr-readiness__counts" data-cr-counts></div>
      </div>

      <div class="cr-toolbar">
        <div class="cr-toolbar__group">
          <span class="cr-toolbar__label">FILTER:</span>
          <div data-cr-filters></div>
        </div>
        <div class="cr-toolbar__group">
          <span class="cr-toolbar__label">SORT:</span>
          <div data-cr-sorts></div>
        </div>
        <input class="cr-search" type="text" placeholder="SEARCH..." data-cr-search>
      </div>

      <div class="cr-body" data-cr-body></div>

      <div class="cr-systems" data-cr-systems>
        <div class="cr-systems__title">SYSTEM EFFECTIVENESS SUMMARY</div>
        <div class="cr-systems__grid" data-cr-sys-grid></div>
      </div>
    </div>
  `;

  document.body.appendChild(_overlay);

  // Wire close button
  _overlay.querySelector('[data-cr-close]').addEventListener('click', _hide);

  // Wire filter buttons
  const filterContainer = _overlay.querySelector('[data-cr-filters]');
  for (const mode of FILTER_MODES) {
    const btn = document.createElement('button');
    btn.className = 'cr-btn' + (mode === _filter ? ' cr-btn--active' : '');
    btn.textContent = mode;
    btn.dataset.crFilter = mode;
    btn.addEventListener('click', () => {
      _filter = mode;
      _updateFilterButtons();
      _render();
    });
    filterContainer.appendChild(btn);
  }

  // Wire sort buttons
  const sortContainer = _overlay.querySelector('[data-cr-sorts]');
  for (const mode of SORT_MODES) {
    const btn = document.createElement('button');
    btn.className = 'cr-btn' + (mode === _sort ? ' cr-btn--active' : '');
    btn.textContent = mode;
    btn.dataset.crSort = mode;
    btn.addEventListener('click', () => {
      _sort = mode;
      _updateSortButtons();
      _render();
    });
    sortContainer.appendChild(btn);
  }

  // Wire search
  const searchEl = _overlay.querySelector('[data-cr-search]');
  searchEl.addEventListener('input', (e) => {
    _search = e.target.value.toLowerCase();
    _render();
  });

  // Wire crew list click delegation
  const bodyEl = _overlay.querySelector('[data-cr-body]');
  bodyEl.addEventListener('click', (e) => {
    const memberEl = e.target.closest('[data-crew-id]');
    if (!memberEl) return;
    const id = memberEl.dataset.crewId;
    _expandedId = (_expandedId === id) ? null : id;
    _selectedId = id;
    _render();
  });
}

// ---------------------------------------------------------------------------
// Show / hide
// ---------------------------------------------------------------------------

function _show() {
  if (!_overlay) return;
  _visible = true;
  _overlay.style.display = 'flex';
  _render();
}

function _hide() {
  if (!_overlay) return;
  _visible = false;
  _overlay.style.display = 'none';
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function _handleCrewRoster(payload) {
  const members = payload.members || payload;
  for (const [id, data] of Object.entries(members)) {
    _crewData[id] = data;
  }
  if (_visible) _render();
}

function _handleRosterUpdate(payload) {
  if (payload.crew_id && _crewData[payload.crew_id]) {
    Object.assign(_crewData[payload.crew_id], payload);
  }
  if (_visible) _render();
}

function _handleShipState(payload) {
  // Extract system power/health for effectiveness display
  if (payload.systems) {
    for (const [name, sys] of Object.entries(payload.systems)) {
      _systemPower[name] = sys.power ?? 100;
      _systemHealth[name] = sys.health ?? 100;
    }
  }
  if (_visible) _render();
}

function _handleGameStarted(payload) {
  _shipName = payload.ship_name || 'TSS Endeavour';
  _shipClass = payload.ship_class || '';
  _crewData = {};
}

// ---------------------------------------------------------------------------
// Keyboard
// ---------------------------------------------------------------------------

function _handleKeydown(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  if ((e.key === 'c' || e.key === 'C') && !e.ctrlKey && !e.metaKey && !e.altKey) {
    // Don't toggle if another overlay is open (puzzle, briefing, etc.)
    const puzzleOpen = document.querySelector('.puzzle-overlay[style*="display: flex"]');
    if (puzzleOpen) return;
    e.preventDefault();
    toggleCrewRoster();
    return;
  }

  if (!_visible) return;

  switch (e.key) {
    case 'Escape':
      e.preventDefault();
      _hide();
      break;
    case 'f':
    case 'F': {
      e.preventDefault();
      const idx = FILTER_MODES.indexOf(_filter);
      _filter = FILTER_MODES[(idx + 1) % FILTER_MODES.length];
      _updateFilterButtons();
      _render();
      break;
    }
    case 's':
    case 'S': {
      // Only cycle sort if search is not focused
      if (document.activeElement === _overlay.querySelector('[data-cr-search]')) return;
      e.preventDefault();
      const idx = SORT_MODES.indexOf(_sort);
      _sort = SORT_MODES[(idx + 1) % SORT_MODES.length];
      _updateSortButtons();
      _render();
      break;
    }
    case 'ArrowDown': {
      e.preventDefault();
      _navigateCrew(1);
      break;
    }
    case 'ArrowUp': {
      e.preventDefault();
      _navigateCrew(-1);
      break;
    }
    case 'Enter': {
      if (_selectedId) {
        _expandedId = (_expandedId === _selectedId) ? null : _selectedId;
        _render();
      }
      break;
    }
  }
}

function _navigateCrew(dir) {
  const members = _getFilteredSorted();
  if (members.length === 0) return;
  const curIdx = members.findIndex(m => m.id === _selectedId);
  let newIdx;
  if (curIdx < 0) {
    newIdx = dir > 0 ? 0 : members.length - 1;
  } else {
    newIdx = (curIdx + dir + members.length) % members.length;
  }
  _selectedId = members[newIdx].id;
  _render();
  // Scroll into view
  const el = _overlay.querySelector(`[data-crew-id="${_selectedId}"]`);
  if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

// ---------------------------------------------------------------------------
// Data processing
// ---------------------------------------------------------------------------

function _getMembers() {
  return Object.values(_crewData);
}

function _getFilteredSorted() {
  let members = _getMembers();

  // Filter
  if (_filter !== 'ALL') {
    const filterMap = {
      'ACTIVE':  m => m.status === 'active',
      'INJURED': m => m.status === 'injured',
      'MEDICAL': m => m.status === 'critical' || m.location === 'medical_bay' || m.location === 'quarantine',
      'KIA':     m => m.status === 'dead',
    };
    const fn = filterMap[_filter];
    if (fn) members = members.filter(fn);
  }

  // Search
  if (_search) {
    members = members.filter(m => {
      const name = `${m.first_name || ''} ${m.surname || ''}`.toLowerCase();
      return name.includes(_search);
    });
  }

  // Sort
  switch (_sort) {
    case 'RANK':
      members.sort((a, b) => (b.rank_level || 0) - (a.rank_level || 0));
      break;
    case 'DECK':
      members.sort((a, b) => (a.deck || 0) - (b.deck || 0));
      break;
    case 'NAME':
      members.sort((a, b) => {
        const na = `${a.surname || ''} ${a.first_name || ''}`;
        const nb = `${b.surname || ''} ${b.first_name || ''}`;
        return na.localeCompare(nb);
      });
      break;
    case 'STATUS': {
      const statusOrder = { dead: 0, critical: 1, injured: 2, active: 3 };
      members.sort((a, b) => (statusOrder[a.status] ?? 9) - (statusOrder[b.status] ?? 9));
      break;
    }
  }

  return members;
}

function _getCrewByDeck() {
  const members = _getFilteredSorted();
  const decks = {};
  for (const m of members) {
    const d = m.deck || 0;
    if (!decks[d]) decks[d] = [];
    decks[d].push(m);
  }
  return decks;
}

function _crewFactorForDeck(deckNum) {
  const allMembers = _getMembers().filter(m => m.deck === deckNum);
  if (allMembers.length === 0) return 1.0;
  let effective = 0;
  for (const m of allMembers) {
    if (m.status === 'dead') continue;
    if (m.location === 'medical_bay' || m.location === 'quarantine' || m.location === 'morgue') continue;
    if (m.status === 'active') {
      effective += 1.0;
    } else {
      effective += 0.5;
    }
  }
  return Math.min(effective / allMembers.length, 1.0);
}

function _crewFactorForSystem(systemName) {
  const dutyStation = SYSTEM_TO_DUTY[systemName];
  if (!dutyStation) return 1.0;
  const assigned = _getMembers().filter(m => m.duty_station === dutyStation);
  if (assigned.length === 0) return 1.0;
  let effective = 0;
  for (const m of assigned) {
    if (m.status === 'dead') continue;
    if (m.location === 'medical_bay' || m.location === 'quarantine' || m.location === 'morgue') continue;
    if (m.status === 'active') {
      effective += 1.0;
    } else {
      effective += 0.5;
    }
  }
  return Math.max(Math.min(effective / assigned.length, 1.0), 0.10);
}

function _systemEffectiveness(systemName) {
  const power = (_systemPower[systemName] ?? 100) / 100;
  const health = (_systemHealth[systemName] ?? 100) / 100;
  const crew = _crewFactorForSystem(systemName);
  return power * health * crew;
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _render() {
  if (!_overlay || !_visible) return;

  const members = _getMembers();
  const total = members.length;
  const active = members.filter(m => m.status === 'active').length;
  const injured = members.filter(m => m.status === 'injured').length;
  const medical = members.filter(m => m.status === 'critical' || m.location === 'medical_bay' || m.location === 'quarantine').length;
  const kia = members.filter(m => m.status === 'dead').length;

  // Header
  const titleEl = _overlay.querySelector('[data-cr-title]');
  titleEl.textContent = `CREW MANIFEST — ${_shipName}`;
  const subtitleEl = _overlay.querySelector('[data-cr-subtitle]');
  subtitleEl.textContent = _shipClass
    ? `${_shipClass.replace(/_/g, ' ')} Class — Crew Complement: ${total}`
    : `Crew Complement: ${total}`;

  // Readiness
  const readiness = total > 0 ? Math.round(((active + injured * 0.5) / total) * 100) : 100;
  const fillEl = _overlay.querySelector('[data-cr-readiness-fill]');
  fillEl.style.width = `${readiness}%`;
  fillEl.style.background = readiness > 75 ? '#00ff41' : readiness > 50 ? '#ffaa00' : '#ff4040';
  _overlay.querySelector('[data-cr-readiness-pct]').textContent = `${readiness}%`;

  const countsEl = _overlay.querySelector('[data-cr-counts]');
  countsEl.innerHTML =
    `<span class="cr-count--active">Active: ${active}</span>` +
    `<span class="cr-count--injured">Injured: ${injured}</span>` +
    `<span class="cr-count--medical">In Medical: ${medical}</span>` +
    `<span class="cr-count--kia">KIA: ${kia}</span>`;

  // Crew list
  _renderCrewList();

  // System effectiveness
  _renderSystems();
}

function _renderCrewList() {
  const bodyEl = _overlay.querySelector('[data-cr-body]');
  const filtered = _getFilteredSorted();

  if (filtered.length === 0) {
    bodyEl.innerHTML = '<div class="cr-empty">No crew match current filters.</div>';
    return;
  }

  // Group by deck for DECK sort, flat list otherwise
  if (_sort === 'DECK') {
    const decks = {};
    for (const m of filtered) {
      const d = m.deck || 0;
      if (!decks[d]) decks[d] = [];
      decks[d].push(m);
    }
    let html = '';
    for (const deckNum of Object.keys(decks).sort((a, b) => a - b)) {
      const factor = _crewFactorForDeck(Number(deckNum));
      const factorPct = Math.round(factor * 100);
      const factorClass = factorPct > 75 ? 'cr-factor--good' : factorPct > 50 ? 'cr-factor--warn' : 'cr-factor--danger';
      html += `<div class="cr-deck">`;
      html += `<div class="cr-deck__header">`;
      html += `<span class="cr-deck__name">DECK ${deckNum} — ${DECK_NAMES[deckNum] || 'UNKNOWN'}</span>`;
      html += `<span class="cr-deck__factor ${factorClass}">Crew Factor: ${factorPct}%</span>`;
      html += `</div>`;
      for (const m of decks[deckNum]) {
        html += _renderMember(m);
      }
      html += `</div>`;
    }
    bodyEl.innerHTML = html;
  } else {
    let html = '';
    for (const m of filtered) {
      html += _renderMember(m);
    }
    bodyEl.innerHTML = html;
  }
}

function _renderMember(m) {
  const isDead = m.status === 'dead';
  const isSelected = m.id === _selectedId;
  const isExpanded = m.id === _expandedId;
  const isSenior = (m.rank_level || 0) >= 5;

  const statusLabel = STATUS_LABELS[m.status] || m.status.toUpperCase();
  const statusCss = STATUS_CSS[m.status] || 'active';

  const rankAbbrev = _abbreviateRank(m.rank || '');
  const stationLabel = DUTY_STATION_LABELS[m.duty_station] || (m.duty_station || '').replace(/_/g, ' ');

  let html = `<div class="cr-member${isSelected ? ' cr-member--selected' : ''}${isDead ? ' cr-member--kia' : ''}" data-crew-id="${_esc(m.id)}">`;
  html += `<span class="cr-member__senior">${isSenior ? '★' : ' '}</span>`;
  html += `<span class="cr-member__name">${_esc(rankAbbrev)} ${_esc(m.first_name || '')} ${_esc(m.surname || '')}</span>`;
  html += `<span class="cr-member__station">${_esc(stationLabel)}</span>`;
  html += `<span class="cr-member__status cr-status--${statusCss}">${statusLabel}${isDead ? ' ✝' : ''}</span>`;
  html += `</div>`;

  // Injury sub-lines (always show for injured/medical/dead)
  if (m.injuries && m.injuries.length > 0) {
    const untreated = m.injuries.filter(i => !i.treated);
    for (const inj of untreated) {
      const region = (inj.body_region || '').replace(/_/g, ' ');
      const desc = inj.description || inj.type.replace(/_/g, ' ');
      const sevClass = `cr-injury__sev--${inj.severity}`;
      const statusNote = inj.treating ? '— In treatment' :
                         m.location === 'medical_bay' ? '— In medical bay' :
                         isDead ? '— Killed in action' :
                         m.status === 'injured' ? '— At station' : '';
      html += `<div class="cr-injury">└─ ${_esc(desc)} (${_esc(region)}) `;
      html += `<span class="cr-injury__sev ${sevClass}">[${(inj.severity || '').toUpperCase()}]</span> `;
      html += `${statusNote}</div>`;
    }
  }

  // Expanded detail
  if (isExpanded) {
    html += `<div class="cr-detail">`;
    html += `<div class="cr-detail__row"><span class="cr-detail__label">Full name:</span> ${_esc(m.rank || '')} ${_esc(m.first_name || '')} ${_esc(m.surname || '')}</div>`;
    html += `<div class="cr-detail__row"><span class="cr-detail__label">Service ID:</span> ${_esc(m.id)}</div>`;
    html += `<div class="cr-detail__row"><span class="cr-detail__label">Deck:</span> Deck ${m.deck} — ${DECK_NAMES[m.deck] || ''}</div>`;
    html += `<div class="cr-detail__row"><span class="cr-detail__label">Duty station:</span> ${_esc(stationLabel)}</div>`;
    html += `<div class="cr-detail__row"><span class="cr-detail__label">Location:</span> ${_esc((m.location || '').replace(/_/g, ' '))}</div>`;
    if (m.treatment_bed != null) {
      html += `<div class="cr-detail__row"><span class="cr-detail__label">Med bed:</span> Bed ${m.treatment_bed}</div>`;
    }
    html += `</div>`;
  }

  return html;
}

function _renderSystems() {
  const gridEl = _overlay.querySelector('[data-cr-sys-grid]');
  let html = '';

  for (const [sys, label] of Object.entries(SYSTEM_LABELS)) {
    const eff = _systemEffectiveness(sys);
    const pct = Math.round(eff * 100);
    const power = Math.round((_systemPower[sys] ?? 100));
    const crew = Math.round(_crewFactorForSystem(sys) * 100);
    const color = pct > 75 ? '#00ff41' : pct > 50 ? '#ffaa00' : '#ff4040';

    html += `<div class="cr-sys-row">`;
    html += `<span class="cr-sys-row__name">${label}</span>`;
    html += `<div class="cr-sys-row__bar"><div class="cr-sys-row__fill" style="width:${pct}%;background:${color}"></div></div>`;
    html += `<span class="cr-sys-row__pct" style="color:${color}">${pct}%</span>`;
    html += `<span class="cr-sys-row__breakdown">(Pwr: ${power}% × Crew: ${crew}%)</span>`;
    html += `</div>`;
  }

  gridEl.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _abbreviateRank(rank) {
  const map = {
    'Commander':           'Cdr.',
    'Lt. Commander':       'LtCdr.',
    'Lieutenant':          'Lt.',
    'Sub-Lieutenant':      'SLt.',
    'Chief Petty Officer': 'CPO',
    'Petty Officer':       'PO',
    'Crewman':             'Crw.',
  };
  return map[rank] || rank;
}

function _updateFilterButtons() {
  if (!_overlay) return;
  _overlay.querySelectorAll('[data-cr-filter]').forEach(btn => {
    btn.classList.toggle('cr-btn--active', btn.textContent === _filter);
  });
}

function _updateSortButtons() {
  if (!_overlay) return;
  _overlay.querySelectorAll('[data-cr-sort]').forEach(btn => {
    btn.classList.toggle('cr-btn--active', btn.textContent === _sort);
  });
}

function _esc(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------------
// Inject CSS
// ---------------------------------------------------------------------------

function _injectCSS() {
  if (document.getElementById('crew-roster-styles')) return;
  const link = document.createElement('link');
  link.id = 'crew-roster-styles';
  link.rel = 'stylesheet';
  link.href = '/client/shared/crew_roster.css';
  document.head.appendChild(link);
}
