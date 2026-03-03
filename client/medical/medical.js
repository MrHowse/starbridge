/**
 * Starbridge — Medical Station v2
 *
 * Individual crew member casualty tracking, body diagram, injury detail,
 * treatment flow, quarantine, and status bar.
 *
 * Server messages received:
 *   game.started           — show medical UI; store mission label
 *   ship.state             — crew counts, medical_supplies (legacy compat)
 *   medical.state          — full v2 medical state
 *   medical.crew_roster    — individual crew member data
 *   medical.event          — severity change, death, treatment complete, etc.
 *   ship.alert_changed     — update station alert colour
 *   ship.hull_hit          — hit-flash border
 *   game.over              — defeat/victory overlay
 *
 * Server messages sent:
 *   lobby.claim_role        { role: 'medical', player_name }
 *   medical.admit           { crew_id }
 *   medical.treat           { crew_id, injury_id }
 *   medical.stabilise       { crew_id, injury_id }
 *   medical.discharge       { crew_id }
 *   medical.quarantine      { crew_id }
 *   medical.treat_crew      { deck, injury_type }          (legacy compat)
 *   medical.cancel_treatment { deck }                       (legacy compat)
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import {
  setStatusDot, setAlertLevel, showBriefing, showGameOver,
} from '../shared/ui_components.js';
import { initPuzzleRenderer } from '../shared/puzzle_renderer.js';
import { SoundBank } from '../shared/audio.js';
import '../shared/audio_events.js';
import { wireButtonSounds } from '../shared/audio_ui.js';
import { registerHelp, initHelpOverlay } from '../shared/help_overlay.js';
import { initNotifications } from '../shared/notifications.js';
import { initRoleBar } from '../shared/role_bar.js';
import { initCrewRoster } from '../shared/crew_roster.js';

registerHelp([
  { selector: '#casualty-list',  text: 'Casualty list — click a crew member to view their injuries. Use sort/filter buttons to organise.', position: 'right' },
  { selector: '#body-diagram',   text: 'Body diagram — shows injury locations. Click a region to filter injuries.', position: 'left' },
  { selector: '#injury-list',    text: 'Injuries for selected patient. Click treatment buttons to begin.', position: 'left' },
  { selector: '.med-status-bar', text: 'Status bar — beds, queue, supplies, quarantine, morgue, crew count.', position: 'above' },
]);

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const HIT_FLASH_MS = 500;
const SEVERITY_ORDER = { critical: 0, serious: 1, moderate: 2, minor: 3 };
const SEVERITY_LABELS = { critical: 'CRITICAL', serious: 'SERIOUS', moderate: 'MODERATE', minor: 'MINOR' };
const SEVERITY_COLORS = {
  critical: '#ff3333',
  serious:  '#ff8800',
  moderate: '#ffaa00',
  minor:    '#888888',
};

// Body diagram region layout (relative to 240x320 canvas)
const BODY_REGIONS = {
  head:      { x: 96,  y: 10,  w: 48, h: 48, label: 'HEAD' },
  torso:     { x: 76,  y: 66,  w: 88, h: 100, label: 'TORSO' },
  left_arm:  { x: 24,  y: 70,  w: 44, h: 90, label: 'L.ARM' },
  right_arm: { x: 172, y: 70,  w: 44, h: 90, label: 'R.ARM' },
  left_leg:  { x: 76,  y: 174, w: 40, h: 120, label: 'L.LEG' },
  right_leg: { x: 124, y: 174, w: 40, h: 120, label: 'R.LEG' },
};

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusDotEl    = document.querySelector('[data-status-dot]');
const statusLabelEl  = document.querySelector('[data-status-label]');
const standbyEl      = document.querySelector('[data-standby]');
const medicalMainEl  = document.querySelector('[data-medical-main]');
const missionLabelEl = document.getElementById('mission-label');
const stationEl      = document.querySelector('.station-container');

const casualtyListEl  = document.getElementById('casualty-list');
const patientNameEl   = document.getElementById('patient-name');
const detailEmptyEl   = document.getElementById('detail-empty');
const detailViewEl    = document.getElementById('detail-view');
const ptRankNameEl    = document.getElementById('pt-rank-name');
const ptStationEl     = document.getElementById('pt-station');
const ptDeckEl        = document.getElementById('pt-deck');
const ptLocationEl    = document.getElementById('pt-location');
const bodyCanvas      = document.getElementById('body-diagram');
const bodyCtx         = bodyCanvas ? bodyCanvas.getContext('2d') : null;
const injuryListEl    = document.getElementById('injury-list');
const btnAdmit        = document.getElementById('btn-admit');
const btnDischarge    = document.getElementById('btn-discharge');
const btnQuarantine   = document.getElementById('btn-quarantine');

// Status bar
const stBedsEl        = document.getElementById('st-beds');
const stQueueEl       = document.getElementById('st-queue');
const supplyFillEl    = document.getElementById('supply-fill');
const supplyCountEl   = document.getElementById('supply-count');
const stQuarantineEl  = document.getElementById('st-quarantine');
const stMorgueEl      = document.getElementById('st-morgue');
const stCrewEl        = document.getElementById('st-crew');
const stTreatWrapEl   = document.getElementById('st-treatment-wrap');
const stTreatLabelEl  = document.getElementById('st-treatment-label');
const stTreatFillEl   = document.getElementById('st-treatment-fill');
const stTreatPctEl    = document.getElementById('st-treatment-pct');
const morgueItemEl    = document.getElementById('morgue-item');
const morgueOverlayEl = document.getElementById('morgue-overlay');
const morgueListEl    = document.getElementById('morgue-list');
const btnCloseMorgue  = document.getElementById('btn-close-morgue');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let crewRoster = {};          // crew_id → crew member dict
let medicalState = {};        // beds, queue, treatments, supplies, quarantine, morgue
let selectedCrewId = null;    // currently selected casualty
let sortMode = 'urgency';     // urgency | deck | name | arrival
let filterSeverity = 'all';   // all | critical | serious | moderate | minor
let filterDeck = 'all';       // all | 1-5
let bodyRegionFilter = null;  // null or body region string
let _renderedDetailId = null;
let _highlightIndex = -1;     // keyboard nav index

// ---------------------------------------------------------------------------
// Sorting & filtering
// ---------------------------------------------------------------------------

function getCasualties() {
  const list = Object.values(crewRoster).filter(m => {
    if (m.status === 'active' && (!m.injuries || m.injuries.length === 0 || m.injuries.every(i => i.treated))) return false;
    return true;
  });

  // Filter by severity
  if (filterSeverity !== 'all') {
    const keep = list.filter(m => {
      if (m.status === 'dead') return filterSeverity === 'critical';
      return m.injuries && m.injuries.some(i => !i.treated && i.severity === filterSeverity);
    });
    return sortCasualties(keep);
  }

  // Filter by deck
  if (filterDeck !== 'all') {
    const deckNum = parseInt(filterDeck, 10);
    const keep = list.filter(m => m.deck === deckNum);
    return sortCasualties(keep);
  }

  return sortCasualties(list);
}

function getWorstSeverity(member) {
  if (member.status === 'dead') return 'critical';
  if (!member.injuries || member.injuries.length === 0) return null;
  const untreated = member.injuries.filter(i => !i.treated);
  if (untreated.length === 0) return null;
  let worst = null;
  for (const inj of untreated) {
    if (worst === null || (SEVERITY_ORDER[inj.severity] ?? 99) < (SEVERITY_ORDER[worst] ?? 99)) {
      worst = inj.severity;
    }
  }
  return worst;
}

function getWorstTimer(member) {
  if (!member.injuries) return Infinity;
  let minTimer = Infinity;
  for (const inj of member.injuries) {
    if (inj.treated || inj.treating) continue;
    if (inj.severity === 'critical' && inj.death_timer != null) {
      minTimer = Math.min(minTimer, inj.death_timer);
    } else if (inj.degrade_timer != null) {
      minTimer = Math.min(minTimer, inj.degrade_timer);
    }
  }
  return minTimer;
}

function sortCasualties(list) {
  switch (sortMode) {
    case 'urgency':
      return list.sort((a, b) => {
        const sa = SEVERITY_ORDER[getWorstSeverity(a)] ?? 99;
        const sb = SEVERITY_ORDER[getWorstSeverity(b)] ?? 99;
        if (sa !== sb) return sa - sb;
        return getWorstTimer(a) - getWorstTimer(b);
      });
    case 'deck':
      return list.sort((a, b) => (a.deck || 0) - (b.deck || 0));
    case 'name':
      return list.sort((a, b) => {
        const na = `${a.surname || ''} ${a.first_name || ''}`;
        const nb = `${b.surname || ''} ${b.first_name || ''}`;
        return na.localeCompare(nb);
      });
    case 'arrival':
      return list.sort((a, b) => {
        const ta = a.injuries && a.injuries.length > 0 ? Math.max(...a.injuries.map(i => i.tick_received || 0)) : 0;
        const tb = b.injuries && b.injuries.length > 0 ? Math.max(...b.injuries.map(i => i.tick_received || 0)) : 0;
        return tb - ta;
      });
    default:
      return list;
  }
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function fmtTimer(seconds) {
  if (seconds == null || seconds === Infinity) return '--:--';
  const s = Math.max(0, Math.ceil(seconds));
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2, '0')}`;
}

function fmtRegion(region) {
  if (!region) return '';
  return region.replace(/_/g, ' ');
}

function displayName(member) {
  const rank = member.rank || '';
  const surname = member.surname || '';
  return `${rank} ${surname}`.trim();
}

// ---------------------------------------------------------------------------
// Rendering: Casualty list
// ---------------------------------------------------------------------------

function renderCasualtyList() {
  const casualties = getCasualties();

  // Empty state
  if (casualties.length === 0) {
    const existing = casualtyListEl.querySelectorAll('.cas-card');
    if (existing.length === 0 && casualtyListEl.querySelector('.med-empty-msg')) return;
    casualtyListEl.innerHTML = '<p class="text-body text-dim med-empty-msg">No casualties reported.</p>';
    return;
  }

  // Remove empty message if present
  const emptyMsg = casualtyListEl.querySelector('.med-empty-msg');
  if (emptyMsg) emptyMsg.remove();

  // Build map of existing cards by crew ID
  const existingCards = new Map();
  casualtyListEl.querySelectorAll('[data-crew-id]').forEach(card => {
    existingCards.set(card.dataset.crewId, card);
  });

  // Current casualty IDs in order
  const currentIds = new Set(casualties.map(c => c.id));

  // Remove cards for crew no longer in the list
  existingCards.forEach((card, id) => {
    if (!currentIds.has(id)) card.remove();
  });

  // Save scroll position
  const scrollPos = casualtyListEl.scrollTop;

  // Update existing or create new cards, in correct order
  let prevNode = null;
  for (const member of casualties) {
    let card = existingCards.get(member.id);
    if (card) {
      _updateCasualtyCard(card, member);
    } else {
      card = _createCasualtyCard(member);
    }

    // Ensure correct DOM order
    const nextSibling = prevNode ? prevNode.nextSibling : casualtyListEl.firstChild;
    if (card !== nextSibling) {
      casualtyListEl.insertBefore(card, nextSibling);
    }
    prevNode = card;
  }

  // Restore scroll position
  casualtyListEl.scrollTop = scrollPos;
}

function _createCasualtyCard(member) {
  const card = document.createElement('div');
  card.className = 'cas-card';
  card.dataset.crewId = member.id;
  card.setAttribute('role', 'option');

  // Build inner structure once (spans will be updated in place)
  card.innerHTML = `
    <div class="cas-card__row1">
      <span class="cas-card__name"></span>
      <span class="cas-card__severity"></span>
    </div>
    <div class="cas-card__row2">
      <span class="cas-card__injury"></span>
      <span class="cas-card__timer"></span>
    </div>
    <div class="cas-card__row3"></div>
    <span class="cas-deceased-overlay">DECEASED</span>
  `;

  card.classList.add('cas-card--entering');
  card.addEventListener('animationend', () => card.classList.remove('cas-card--entering'), { once: true });

  _updateCasualtyCard(card, member);
  return card;
}

function _updateCasualtyCard(card, member) {
  const worst = getWorstSeverity(member);
  const isDead = member.status === 'dead';
  const isSelected = member.id === selectedCrewId;

  // Severity class (only change if different)
  const sevClasses = ['cas-card--critical', 'cas-card--serious', 'cas-card--moderate', 'cas-card--minor', 'cas-card--dead'];
  const wantClass = isDead ? 'cas-card--dead' : worst ? `cas-card--${worst}` : null;
  for (const cls of sevClasses) {
    card.classList.toggle(cls, cls === wantClass);
  }
  card.classList.toggle('cas-card--selected', isSelected);
  card.setAttribute('aria-selected', isSelected ? 'true' : 'false');

  // Row 1: Name + severity badge
  const nameEl = card.querySelector('.cas-card__name');
  const sevEl = card.querySelector('.cas-card__severity');
  const name = displayName(member);
  if (nameEl.textContent !== name) nameEl.textContent = name;

  if (isDead) {
    sevEl.className = 'cas-card__severity sev--critical';
    if (sevEl.textContent !== 'DECEASED') sevEl.textContent = 'DECEASED';
  } else if (worst) {
    sevEl.className = `cas-card__severity sev--${worst}`;
    const label = SEVERITY_LABELS[worst] || worst.toUpperCase();
    if (sevEl.textContent !== label) sevEl.textContent = label;
  } else {
    sevEl.className = 'cas-card__severity';
    sevEl.textContent = '';
  }

  // Row 2: Worst injury + timer
  const injEl = card.querySelector('.cas-card__injury');
  const timerEl = card.querySelector('.cas-card__timer');

  const worstInj = !isDead && member.injuries
    ? member.injuries.filter(i => !i.treated).sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 99) - (SEVERITY_ORDER[b.severity] ?? 99))[0]
    : null;
  const injDesc = worstInj ? worstInj.description || worstInj.type.replace(/_/g, ' ') : '';
  if (injEl.textContent !== injDesc) injEl.textContent = injDesc;

  if (!isDead && worstInj && worstInj.severity === 'critical' && worstInj.death_timer != null) {
    timerEl.className = 'cas-card__timer cas-card__timer--death';
    timerEl.textContent = fmtTimer(worstInj.death_timer);
  } else if (!isDead && worstInj && worstInj.degrade_timer != null) {
    timerEl.className = 'cas-card__timer cas-card__timer--degrade';
    timerEl.textContent = fmtTimer(worstInj.degrade_timer);
  } else {
    timerEl.className = 'cas-card__timer';
    timerEl.textContent = '';
  }

  // Row 3: Deck + station
  const row3El = card.querySelector('.cas-card__row3');
  const deckLabel = member.deck != null ? `Deck ${member.deck}` : '';
  const stationLabel = member.duty_station ? member.duty_station.replace(/_/g, ' ') : '';
  const row3Text = `${deckLabel}${stationLabel ? ' — ' + stationLabel : ''}`;
  if (row3El.textContent !== row3Text) row3El.textContent = row3Text;
}

// ---------------------------------------------------------------------------
// Rendering: Patient detail
// ---------------------------------------------------------------------------

function renderPatientDetail() {
  if (!selectedCrewId || !crewRoster[selectedCrewId]) {
    detailEmptyEl.style.display = '';
    detailViewEl.style.display = 'none';
    patientNameEl.textContent = 'No patient selected';
    return;
  }

  detailEmptyEl.style.display = 'none';
  detailViewEl.style.display = '';

  const member = crewRoster[selectedCrewId];
  patientNameEl.textContent = displayName(member);
  ptRankNameEl.textContent = `${member.rank || ''} ${member.first_name || ''} ${member.surname || ''}`.trim();
  ptStationEl.textContent = member.duty_station ? member.duty_station.replace(/_/g, ' ').toUpperCase() : '';
  ptDeckEl.textContent = member.deck != null ? `DECK ${member.deck}` : '';
  ptLocationEl.textContent = member.location ? member.location.replace(/_/g, ' ').toUpperCase() : '';

  // Body diagram is rendered by the dedicated animation loop (_startDiagramLoop)
  // at 60fps for smooth pulse animation — do NOT call renderBodyDiagram here.
  renderInjuryList(member);
  updateActionButtons(member);
}

// ---------------------------------------------------------------------------
// Rendering: Body diagram
// ---------------------------------------------------------------------------

function renderBodyDiagram(member) {
  if (!bodyCtx) return;
  const w = bodyCanvas.width;
  const h = bodyCanvas.height;
  bodyCtx.clearRect(0, 0, w, h);

  // Build injury map: region → worst severity + count
  const regionMap = {};
  if (member.injuries) {
    for (const inj of member.injuries) {
      if (inj.treated) continue;
      const region = inj.body_region;
      if (region === 'whole_body') {
        // Highlight all regions
        for (const r of Object.keys(BODY_REGIONS)) {
          _addToRegionMap(regionMap, r, inj.severity);
        }
      } else if (BODY_REGIONS[region]) {
        _addToRegionMap(regionMap, region, inj.severity);
      }
    }
  }

  // Draw each region
  const now = Date.now();
  for (const [regionId, reg] of Object.entries(BODY_REGIONS)) {
    const info = regionMap[regionId];
    const isFiltered = bodyRegionFilter && bodyRegionFilter !== regionId;

    if (regionId === 'head') {
      _drawHeadRegion(reg, info, now, isFiltered);
    } else {
      _drawRectRegion(reg, info, now, isFiltered);
    }

    // Region label
    bodyCtx.font = '9px monospace';
    bodyCtx.fillStyle = isFiltered ? 'rgba(100,100,100,0.3)' : 'rgba(200,200,200,0.6)';
    bodyCtx.textAlign = 'center';
    const labelY = regionId.includes('leg') ? reg.y + reg.h + 12 : reg.y - 4;
    bodyCtx.fillText(reg.label, reg.x + reg.w / 2, labelY);

    // Injury count badge
    if (info && info.count > 1) {
      const bx = reg.x + reg.w - 6;
      const by = reg.y + 2;
      bodyCtx.fillStyle = SEVERITY_COLORS[info.worst] || '#888';
      bodyCtx.fillRect(bx - 2, by - 8, 14, 12);
      bodyCtx.fillStyle = '#000';
      bodyCtx.font = 'bold 9px monospace';
      bodyCtx.fillText(String(info.count), bx + 4, by + 1);
    }
  }
}

function _addToRegionMap(map, region, severity) {
  if (!map[region]) {
    map[region] = { worst: severity, count: 1 };
  } else {
    map[region].count++;
    if ((SEVERITY_ORDER[severity] ?? 99) < (SEVERITY_ORDER[map[region].worst] ?? 99)) {
      map[region].worst = severity;
    }
  }
}

function _drawHeadRegion(reg, info, now, dimmed) {
  const cx = reg.x + reg.w / 2;
  const cy = reg.y + reg.h / 2;
  const r = reg.w / 2;

  bodyCtx.beginPath();
  bodyCtx.arc(cx, cy, r, 0, Math.PI * 2);

  if (info && !dimmed) {
    const alpha = _pulseAlpha(info.worst, now);
    const color = SEVERITY_COLORS[info.worst] || '#888';
    bodyCtx.fillStyle = _withAlpha(color, alpha * 0.4);
    bodyCtx.fill();
    bodyCtx.strokeStyle = _withAlpha(color, alpha);
    bodyCtx.lineWidth = 2;
  } else {
    bodyCtx.strokeStyle = dimmed ? 'rgba(60,60,60,0.3)' : 'rgba(100,100,100,0.5)';
    bodyCtx.lineWidth = 1;
  }
  bodyCtx.stroke();
}

function _drawRectRegion(reg, info, now, dimmed) {
  if (info && !dimmed) {
    const alpha = _pulseAlpha(info.worst, now);
    const color = SEVERITY_COLORS[info.worst] || '#888';
    bodyCtx.fillStyle = _withAlpha(color, alpha * 0.4);
    bodyCtx.fillRect(reg.x, reg.y, reg.w, reg.h);
    bodyCtx.strokeStyle = _withAlpha(color, alpha);
    bodyCtx.lineWidth = 2;
  } else {
    bodyCtx.strokeStyle = dimmed ? 'rgba(60,60,60,0.3)' : 'rgba(100,100,100,0.5)';
    bodyCtx.lineWidth = 1;
  }
  bodyCtx.strokeRect(reg.x, reg.y, reg.w, reg.h);
}

function _pulseAlpha(severity, now) {
  const speed = { critical: 3, serious: 1.5, moderate: 0.8, minor: 0.4 }[severity] || 0.5;
  return 0.5 + 0.5 * Math.sin(now / 1000 * speed * Math.PI * 2);
}

function _withAlpha(hex, alpha) {
  // Convert #rrggbb to rgba
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha.toFixed(2)})`;
}

// ---------------------------------------------------------------------------
// Rendering: Injury list
// ---------------------------------------------------------------------------

let _injuryListHash = '';

function renderInjuryList(member) {
  if (!member.injuries || member.injuries.length === 0) {
    if (injuryListEl.querySelector('.inj-card')) injuryListEl.innerHTML = '';
    if (!injuryListEl.querySelector('.text-dim')) {
      injuryListEl.innerHTML = '<p class="text-body text-dim">No injuries.</p>';
    }
    _injuryListHash = '';
    return;
  }

  // Sort: untreated first, by severity
  const sorted = [...member.injuries].sort((a, b) => {
    if (a.treated !== b.treated) return a.treated ? 1 : -1;
    return (SEVERITY_ORDER[a.severity] ?? 99) - (SEVERITY_ORDER[b.severity] ?? 99);
  });

  // Filter by body region if set
  const filtered = bodyRegionFilter
    ? sorted.filter(i => i.body_region === bodyRegionFilter || i.body_region === 'whole_body')
    : sorted;

  // Hash over the data that actually changes to skip no-op rebuilds
  const treatment = _findTreatment(member.id);
  const tElapsed = treatment ? Math.round(treatment.elapsed) : -1;
  const hash = filtered.map(i =>
    `${i.id}:${i.severity}:${i.treated}:${i.treating}:${Math.ceil(i.death_timer ?? -1)}:${Math.ceil(i.degrade_timer ?? -1)}`
  ).join('|') + `|bed=${member.treatment_bed}|te=${tElapsed}|rf=${bodyRegionFilter}`;
  if (hash === _injuryListHash) return;
  _injuryListHash = hash;

  injuryListEl.innerHTML = '';

  for (const inj of filtered) {
    const card = document.createElement('div');
    card.className = 'inj-card';
    if (inj.treated) card.classList.add('inj-card--treated');
    if (inj.treating) card.classList.add('inj-card--treating');

    const sevClass = `sev--${inj.severity}`;
    const typeName = (inj.type || '').replace(/_/g, ' ');
    const regionLabel = fmtRegion(inj.body_region);

    // Timer
    let timerHtml = '';
    if (!inj.treated && !inj.treating) {
      if (inj.severity === 'critical' && inj.death_timer != null) {
        timerHtml = `<span class="inj-card__timer inj-card__timer--death">Death in: ${fmtTimer(inj.death_timer)}</span>`;
      } else if (inj.degrade_timer != null) {
        timerHtml = `<span class="inj-card__timer inj-card__timer--degrade">Degrades in: ${fmtTimer(inj.degrade_timer)}</span>`;
      }
    }

    // Treatment actions or progress
    let actionsHtml = '';
    if (inj.treated) {
      actionsHtml = '<span class="text-label" style="color:var(--system-healthy)">TREATED</span>';
    } else if (inj.treating) {
      const pct = treatment ? Math.min(100, Math.round((treatment.elapsed / treatment.duration) * 100)) : 0;
      const puzzleWait = treatment && treatment.puzzle_required && !treatment.puzzle_completed;
      const label = puzzleWait ? 'AWAITING PROCEDURE' : `${pct}%`;
      actionsHtml = `
        <div class="inj-progress">
          <div class="gauge"><div class="gauge__fill" style="width:${puzzleWait ? 0 : pct}%"></div></div>
          <span class="inj-progress__pct">${label}</span>
        </div>
      `;
    } else {
      const treatType = inj.treatment_type || 'first_aid';
      const treatDur = inj.treatment_duration ? Math.round(inj.treatment_duration) : '?';
      const treatLabel = treatType === 'stabilise'
        ? 'TREAT'
        : treatType.replace(/_/g, ' ').toUpperCase();
      const inBed = member.treatment_bed != null;
      const hasTreatment = treatment != null;

      actionsHtml = `
        <div class="inj-card__actions">
          <button class="btn" data-action="treat" data-crew-id="${member.id}" data-injury-id="${inj.id}"
                  ${(!inBed || hasTreatment) ? 'disabled' : ''}>${treatLabel} ${treatDur}s</button>
          <button class="btn" data-action="stabilise" data-crew-id="${member.id}" data-injury-id="${inj.id}"
                  >STABILISE</button>
        </div>
      `;
    }

    card.innerHTML = `
      <div class="inj-card__header">
        <span class="inj-card__type">${typeName} <span class="cas-card__severity ${sevClass}">${SEVERITY_LABELS[inj.severity] || ''}</span></span>
        <span class="inj-card__region">${regionLabel}</span>
      </div>
      <div class="inj-card__desc">${inj.description || ''}</div>
      ${timerHtml}
      ${actionsHtml}
    `;

    injuryListEl.appendChild(card);
  }
}

function _findTreatment(crewId) {
  if (!medicalState.active_treatments) return null;
  return medicalState.active_treatments[crewId] || null;
}

// ---------------------------------------------------------------------------
// Rendering: Action buttons
// ---------------------------------------------------------------------------

function updateActionButtons(member) {
  const isDead = member.status === 'dead';
  const inBay = member.location === 'medical_bay';
  const inQuarantine = member.location === 'quarantine';
  const allTreated = member.injuries && member.injuries.length > 0 && member.injuries.every(i => i.treated);
  const hasContagion = member.injuries && member.injuries.some(i =>
    !i.treated && i.type && i.type.startsWith('infection_stage')
  );

  btnAdmit.disabled = isDead || inBay || inQuarantine;
  btnDischarge.disabled = isDead || (!inBay && !inQuarantine) || !allTreated;
  btnQuarantine.disabled = isDead || inQuarantine || !hasContagion;
}

// ---------------------------------------------------------------------------
// Rendering: Status bar
// ---------------------------------------------------------------------------

function renderStatusBar() {
  const beds = medicalState.beds_total || 4;
  const occupied = medicalState.beds_occupied ? Object.keys(medicalState.beds_occupied).length : 0;
  const bedDots = Array.from({ length: beds }, (_, i) => i < occupied ? '\u25CF' : '\u25CB').join('');
  stBedsEl.textContent = `${bedDots} ${occupied}/${beds}`;

  const queueLen = medicalState.queue ? medicalState.queue.length : 0;
  stQueueEl.textContent = String(queueLen);

  // Supplies
  const supplies = medicalState.supplies ?? 100;
  const suppliesMax = medicalState.supplies_max ?? 100;
  const pct = Math.max(0, Math.round((supplies / suppliesMax) * 100));
  supplyFillEl.style.width = `${pct}%`;
  supplyCountEl.textContent = `${pct}%`;
  if (pct > 50) {
    supplyFillEl.className = 'gauge__fill gauge__fill--supply';
  } else if (pct > 25) {
    supplyFillEl.className = 'gauge__fill gauge__fill--supply gauge__fill--warn';
  } else {
    supplyFillEl.className = 'gauge__fill gauge__fill--supply gauge__fill--danger';
  }

  // Quarantine
  const qTotal = medicalState.quarantine_total || 2;
  const qOccupied = medicalState.quarantine_occupied ? Object.keys(medicalState.quarantine_occupied).length : 0;
  stQuarantineEl.textContent = `${qOccupied}/${qTotal}`;

  // Morgue
  const morgueCount = medicalState.morgue ? medicalState.morgue.length : 0;
  stMorgueEl.textContent = String(morgueCount);

  // Crew count
  const totalCrew = Object.keys(crewRoster).length;
  const activeCrew = Object.values(crewRoster).filter(m => m.status === 'active').length;
  stCrewEl.textContent = `${activeCrew}/${totalCrew}`;

  // Treatment progress in status bar
  const treatments = medicalState.active_treatments || {};
  const treatIds = Object.keys(treatments);
  if (treatIds.length > 0) {
    stTreatWrapEl.style.display = '';
    // Show first active treatment
    const t = treatments[treatIds[0]];
    const member = crewRoster[t.crew_member_id];
    const name = member ? displayName(member) : '?';
    const treatLabel = (t.treatment_type || '').replace(/_/g, ' ');
    const tPct = t.duration > 0 ? Math.min(100, Math.round((t.elapsed / t.duration) * 100)) : 0;
    stTreatLabelEl.textContent = `${name} — ${treatLabel}`;
    stTreatFillEl.style.width = `${tPct}%`;
    stTreatPctEl.textContent = `${tPct}%`;
  } else {
    stTreatWrapEl.style.display = 'none';
  }
}

// ---------------------------------------------------------------------------
// Rendering: Morgue overlay
// ---------------------------------------------------------------------------

function renderMorgueList() {
  const morgueIds = medicalState.morgue || [];
  if (morgueIds.length === 0) {
    morgueListEl.innerHTML = '<p class="text-body text-dim">No casualties.</p>';
    return;
  }
  morgueListEl.innerHTML = '';
  for (const cid of morgueIds) {
    const member = crewRoster[cid];
    if (!member) continue;
    const name = `${member.rank || ''} ${member.first_name || ''} ${member.surname || ''}`.trim();
    const cause = member.injuries ? member.injuries.filter(i => i.severity === 'critical').map(i => i.description || i.type.replace(/_/g, ' ')).join(', ') : 'Unknown';

    const row = document.createElement('div');
    row.className = 'morgue-row';
    row.innerHTML = `
      <span class="morgue-row__name">${name}</span>
      <span class="morgue-row__cause">${cause}</span>
    `;
    morgueListEl.appendChild(row);
  }
}

// ---------------------------------------------------------------------------
// Master render
// ---------------------------------------------------------------------------

function render() {
  renderCasualtyList();
  renderPatientDetail();
  renderStatusBar();
}

// Body diagram animation loop (separate from data render)
let _animFrame = null;
function _startDiagramLoop() {
  function frame() {
    if (selectedCrewId && crewRoster[selectedCrewId]) {
      renderBodyDiagram(crewRoster[selectedCrewId]);
    }
    _animFrame = requestAnimationFrame(frame);
  }
  if (!_animFrame) _animFrame = requestAnimationFrame(frame);
}

// ---------------------------------------------------------------------------
// Interaction
// ---------------------------------------------------------------------------

function selectCrew(crewId) {
  selectedCrewId = (selectedCrewId === crewId) ? null : crewId;
  bodyRegionFilter = null;
  _renderedDetailId = null;
  render();
}

// Body diagram click → region filter
if (bodyCanvas) {
  bodyCanvas.addEventListener('click', (e) => {
    const rect = bodyCanvas.getBoundingClientRect();
    const scaleX = bodyCanvas.width / rect.width;
    const scaleY = bodyCanvas.height / rect.height;
    const mx = (e.clientX - rect.left) * scaleX;
    const my = (e.clientY - rect.top) * scaleY;

    for (const [regionId, reg] of Object.entries(BODY_REGIONS)) {
      if (regionId === 'head') {
        const cx = reg.x + reg.w / 2;
        const cy = reg.y + reg.h / 2;
        const r = reg.w / 2;
        if (Math.hypot(mx - cx, my - cy) <= r) {
          bodyRegionFilter = bodyRegionFilter === regionId ? null : regionId;
          render();
          return;
        }
      } else {
        if (mx >= reg.x && mx <= reg.x + reg.w && my >= reg.y && my <= reg.y + reg.h) {
          bodyRegionFilter = bodyRegionFilter === regionId ? null : regionId;
          render();
          return;
        }
      }
    }
    // Click outside regions → clear filter
    bodyRegionFilter = null;
    render();
  });
}

// Injury list action buttons (delegated)
if (injuryListEl) {
  injuryListEl.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn || btn.disabled) return;
    const action = btn.dataset.action;
    const crewId = btn.dataset.crewId;
    const injuryId = btn.dataset.injuryId;
    if (action === 'treat') {
      send('medical.treat', { crew_id: crewId, injury_id: injuryId });
    } else if (action === 'stabilise') {
      send('medical.stabilise', { crew_id: crewId, injury_id: injuryId });
      // Flash the timer element green and play confirmation sound
      const card = btn.closest('.inj-card');
      if (card) {
        const timer = card.querySelector('.inj-card__timer');
        if (timer) {
          timer.classList.add('inj-card__timer--stabilised');
          setTimeout(() => timer.classList.remove('inj-card__timer--stabilised'), 1200);
        }
      }
      SoundBank.play('scan_complete');
    }
  });
}

// Casualty list click (delegated)
if (casualtyListEl) {
  casualtyListEl.addEventListener('click', (e) => {
    const card = e.target.closest('.cas-card');
    if (card && card.dataset.crewId) selectCrew(card.dataset.crewId);
  });
}

// Sort buttons
document.querySelectorAll('[data-sort]').forEach(btn => {
  btn.addEventListener('click', () => {
    sortMode = btn.dataset.sort;
    document.querySelectorAll('[data-sort]').forEach(b => b.classList.remove('med-sort-btn--active'));
    btn.classList.add('med-sort-btn--active');
    render();
  });
});

// Severity filter buttons
document.querySelectorAll('[data-filter]').forEach(btn => {
  btn.addEventListener('click', () => {
    filterSeverity = btn.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach(b => b.classList.remove('med-filter-btn--active'));
    btn.classList.add('med-filter-btn--active');
    render();
  });
});

// Deck filter buttons
document.querySelectorAll('[data-deck]').forEach(btn => {
  btn.addEventListener('click', () => {
    filterDeck = btn.dataset.deck;
    document.querySelectorAll('[data-deck]').forEach(b => b.classList.remove('med-filter-btn--active'));
    btn.classList.add('med-filter-btn--active');
    render();
  });
});

// Action buttons
if (btnAdmit) {
  btnAdmit.addEventListener('click', () => {
    if (selectedCrewId) send('medical.admit', { crew_id: selectedCrewId });
  });
}

if (btnDischarge) {
  btnDischarge.addEventListener('click', () => {
    if (selectedCrewId) send('medical.discharge', { crew_id: selectedCrewId });
  });
}

if (btnQuarantine) {
  btnQuarantine.addEventListener('click', () => {
    if (selectedCrewId) send('medical.quarantine', { crew_id: selectedCrewId });
  });
}

// Morgue toggle
if (morgueItemEl) {
  morgueItemEl.addEventListener('click', () => {
    renderMorgueList();
    morgueOverlayEl.style.display = '';
  });
}

if (btnCloseMorgue) {
  btnCloseMorgue.addEventListener('click', () => {
    morgueOverlayEl.style.display = 'none';
  });
}

// Close morgue on overlay background click
if (morgueOverlayEl) {
  morgueOverlayEl.addEventListener('click', (e) => {
    if (e.target === morgueOverlayEl) morgueOverlayEl.style.display = 'none';
  });
}

// ---------------------------------------------------------------------------
// Keyboard shortcuts
// ---------------------------------------------------------------------------

document.addEventListener('keydown', (e) => {
  // Don't intercept when typing in inputs
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  const casualties = getCasualties();

  switch (e.key) {
    case 'ArrowUp': {
      e.preventDefault();
      if (casualties.length === 0) return;
      const curIdx = casualties.findIndex(c => c.id === selectedCrewId);
      const newIdx = curIdx <= 0 ? casualties.length - 1 : curIdx - 1;
      selectCrew(casualties[newIdx].id);
      _scrollToCard(casualties[newIdx].id);
      break;
    }
    case 'ArrowDown': {
      e.preventDefault();
      if (casualties.length === 0) return;
      const curIdx = casualties.findIndex(c => c.id === selectedCrewId);
      const newIdx = curIdx >= casualties.length - 1 ? 0 : curIdx + 1;
      selectCrew(casualties[newIdx].id);
      _scrollToCard(casualties[newIdx].id);
      break;
    }
    case 'Enter':
      // Already selected, do nothing extra
      break;
    case 'a':
    case 'A':
      if (selectedCrewId && btnAdmit && !btnAdmit.disabled) btnAdmit.click();
      break;
    case 'd':
    case 'D':
      if (selectedCrewId && btnDischarge && !btnDischarge.disabled) btnDischarge.click();
      break;
    case 'q':
    case 'Q':
      if (selectedCrewId && btnQuarantine && !btnQuarantine.disabled) btnQuarantine.click();
      break;
    case 's':
    case 'S': {
      // Stabilise worst untreated injury
      if (!selectedCrewId) break;
      const member = crewRoster[selectedCrewId];
      if (!member || !member.injuries) break;
      const worst = member.injuries
        .filter(i => !i.treated && !i.treating)
        .sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 99) - (SEVERITY_ORDER[b.severity] ?? 99))[0];
      if (worst) send('medical.stabilise', { crew_id: selectedCrewId, injury_id: worst.id });
      break;
    }
    case 't':
    case 'T': {
      // Treat worst untreated injury
      if (!selectedCrewId) break;
      const member = crewRoster[selectedCrewId];
      if (!member || !member.injuries || member.treatment_bed == null) break;
      if (_findTreatment(selectedCrewId)) break;
      const worst = member.injuries
        .filter(i => !i.treated && !i.treating)
        .sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 99) - (SEVERITY_ORDER[b.severity] ?? 99))[0];
      if (worst) send('medical.treat', { crew_id: selectedCrewId, injury_id: worst.id });
      break;
    }
    case '0':
      _clickFilter('[data-deck="all"]');
      break;
    case '1': case '2': case '3': case '4': case '5':
      _clickFilter(`[data-deck="${e.key}"]`);
      break;
    default:
      break;
  }
});

function _scrollToCard(crewId) {
  const card = casualtyListEl.querySelector(`[data-crew-id="${crewId}"]`);
  if (card) card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function _clickFilter(selector) {
  const btn = document.querySelector(selector);
  if (btn) btn.click();
}

// ---------------------------------------------------------------------------
// WebSocket message handlers
// ---------------------------------------------------------------------------

function handleShipState(payload) {
  // Legacy compat: update medical supplies from ship.state if present
  if (payload.medical_supplies !== undefined && !medicalState.supplies) {
    medicalState.supplies = payload.medical_supplies;
    medicalState.supplies_max = 20; // old system max
  }
  render();
}

function handleMedicalState(payload) {
  medicalState = payload;
  render();
}

function handleCrewRoster(payload) {
  // payload is { members: { id: memberDict, ... } } or flat { id: memberDict, ... }
  const members = payload.members || payload;
  for (const [id, data] of Object.entries(members)) {
    crewRoster[id] = data;
  }
  render();
}

function handleMedicalEvent(payload) {
  const event = payload.event;

  switch (event) {
    case 'severity_changed':
      SoundBank.play('system_damage');
      break;
    case 'crew_death':
      SoundBank.play('defeat');
      break;
    case 'treatment_complete':
      SoundBank.play('puzzle_success');
      break;
    case 'patient_admitted':
      SoundBank.play('scan_complete');
      break;
    case 'contagion_spread':
      SoundBank.play('boarding_alert');
      break;
    default:
      break;
  }

  _renderedDetailId = null;
}

function handleGameStarted(payload) {
  standbyEl.style.display = 'none';
  medicalMainEl.style.display = '';
  if (payload.mission_name) missionLabelEl.textContent = payload.mission_name;
  showBriefing(payload.mission_name, payload.briefing_text);
  _startDiagramLoop();

  // Ship-class-specific panels
  const isMedShip = (payload.ship_class === 'medical_ship');
  const surgicalPanel = document.getElementById('surgical-theatre-panel');
  const triagePanel   = document.getElementById('triage-ai-panel');
  if (surgicalPanel) surgicalPanel.style.display = isMedShip ? '' : 'none';
  if (triagePanel)   triagePanel.style.display   = isMedShip ? '' : 'none';
}

function handleHullHit() {
  SoundBank.play('hull_hit');
  stationEl.classList.add('hit');
  setTimeout(() => stationEl.classList.remove('hit'), HIT_FLASH_MS);
}

function handleMedicalShipState(payload) {
  const panel = document.getElementById('medical-ship-panel');
  if (!panel) return;
  if (!payload || !payload.active) {
    panel.style.display = 'none';
    return;
  }
  panel.style.display = '';
  const body = document.getElementById('medical-ship-content');
  if (!body) return;
  const beacon = payload.rescue_beacon ? 'ACTIVE' : 'OFF';
  const theatre = payload.surgical_theatre ? 'ACTIVE' : 'OFF';
  const triage = payload.triage_ai ? 'ACTIVE' : 'OFF';
  body.innerHTML =
    `<div class="text-label">Rescue Beacon: <span class="text-data">${beacon}</span></div>` +
    `<div class="text-label">Surgical Theatre: <span class="text-data">${theatre}</span></div>` +
    `<div class="text-label">Triage AI: <span class="text-data">${triage}</span></div>`;
}

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();
  });

  on('game.started',          handleGameStarted);
  on('ship.state',            handleShipState);
  on('medical.state',         handleMedicalState);
  on('medical.crew_roster',   handleCrewRoster);
  on('medical.event',         handleMedicalEvent);
  on('ship.alert_changed',    (p) => setAlertLevel(p.level));
  on('ship.hull_hit',         handleHullHit);
  on('medical_ship.state',    handleMedicalShipState);
  on('game.over',             (p) => { SoundBank.play(p.result === 'victory' ? 'victory' : 'defeat'); showGameOver(p.result, p.stats); });

  initPuzzleRenderer(send);

  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();
  initNotifications(send, 'medical');
  initRoleBar(send, 'medical');
  initCrewRoster(send);

  on('lobby.welcome', () => {
    const name = sessionStorage.getItem('player_name') || 'MEDIC';
    send('lobby.claim_role', { role: 'medical', player_name: name });
  });

  connect();
}

document.addEventListener('DOMContentLoaded', init);
