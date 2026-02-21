/**
 * Starbridge — Medical Station
 *
 * Displays crew status by deck and allows Medical to start/cancel treatment
 * sessions that heal injured or stabilise critical crew over time.
 *
 * Server messages received:
 *   game.started          — show medical UI; store mission label
 *   ship.state            — crew counts, crew_factor, medical_supplies,
 *                           active_treatments
 *   ship.alert_changed    — update station alert colour
 *   ship.hull_hit         — hit-flash border
 *   game.over             — defeat/victory overlay
 *
 * Server messages sent:
 *   lobby.claim_role      { role: 'medical', player_name }
 *   medical.treat_crew    { deck, injury_type: 'injured'|'critical' }
 *   medical.cancel_treatment { deck }
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

registerHelp([
  { selector: '#deck-list',         text: 'Crew by deck — shows active, injured, critical, dead counts.', position: 'right' },
  { selector: '#supply-count',      text: 'Medical supplies — each treatment costs 2 units.', position: 'below' },
  { selector: '#btn-treat-injured', text: 'Start treatment for injured crew on selected deck.', position: 'above' },
  { selector: '#btn-treat-critical',text: 'Start treatment for critical crew (higher priority).', position: 'above' },
]);

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SUPPLY_MAX    = 20;
const HIT_FLASH_MS  = 500;

// Deck display order and labels
const DECK_ORDER = ['bridge', 'sensors', 'weapons', 'shields', 'engineering', 'medical'];
const DECK_LABELS = {
  bridge:      'Bridge',
  sensors:     'Sensors',
  weapons:     'Weapons',
  shields:     'Shields',
  engineering: 'Engineering',
  medical:     'Medical',
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

const supplyFillEl   = document.getElementById('supply-fill');
const supplyCountEl  = document.getElementById('supply-count');
const deckListEl     = document.getElementById('deck-list');

const diseaseListEl     = document.getElementById('disease-list');

const treatmentNoneEl   = document.getElementById('treatment-none');
const treatmentActiveEl = document.getElementById('treatment-active');
const treatDeckLabelEl  = document.getElementById('treatment-deck-label');
const trActiveEl        = document.getElementById('tr-active');
const trInjuredEl       = document.getElementById('tr-injured');
const trCriticalEl      = document.getElementById('tr-critical');
const trDeadEl          = document.getElementById('tr-dead');
const trStatusEl        = document.getElementById('tr-status');
const btnTreatInjuredEl = document.getElementById('btn-treat-injured');
const btnTreatCritEl    = document.getElementById('btn-treat-critical');
const btnCancelEl       = document.getElementById('btn-cancel');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let selectedDeck = null;     // deck name or null
let latestCrewData = {};     // deck_name → { active, injured, critical, dead, crew_factor }
let activeTreatments = {};   // deck_name → 'injured' | 'critical'
let medicalSupplies = SUPPLY_MAX;
let diseaseState = {};       // { infected_decks: {...} }
let _renderedDeckJson = '';  // hash guard — skip DOM rebuild when nothing changed

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderSupplies() {
  const pct = Math.max(0, (medicalSupplies / SUPPLY_MAX) * 100);
  supplyFillEl.style.width = `${pct}%`;
  supplyCountEl.textContent = `${medicalSupplies}/${SUPPLY_MAX}`;
  // Colour-code the supply bar
  if (pct > 50) {
    supplyFillEl.className = 'gauge__fill gauge__fill--supply';
  } else if (pct > 25) {
    supplyFillEl.className = 'gauge__fill gauge__fill--supply gauge__fill--warn';
  } else {
    supplyFillEl.className = 'gauge__fill gauge__fill--supply gauge__fill--danger';
  }
}

function renderDeckList() {
  // Round crew_factor to 2 dp so floating-point jitter doesn't trigger
  // a DOM rebuild every tick.
  const roundedCrew = {};
  for (const [deck, data] of Object.entries(latestCrewData)) {
    roundedCrew[deck] = { ...data, crew_factor: Math.round(data.crew_factor * 100) / 100 };
  }

  // Skip full DOM rebuild when nothing has actually changed.
  const key = JSON.stringify({ crew: roundedCrew, treatments: activeTreatments, selected: selectedDeck });
  if (key === _renderedDeckJson) return;
  _renderedDeckJson = key;

  deckListEl.innerHTML = '';
  for (const deckName of DECK_ORDER) {
    const crew = latestCrewData[deckName];
    if (!crew) continue;

    const isSelected = (deckName === selectedDeck);
    const treatment = activeTreatments[deckName];
    const factorPct = Math.round(crew.crew_factor * 100);

    const card = document.createElement('div');
    card.className = 'deck-card' + (isSelected ? ' deck-card--selected' : '');
    card.dataset.deck = deckName;

    const treatBadge = treatment
      ? `<span class="treatment-badge treatment-badge--${treatment}">${treatment.toUpperCase()}</span>`
      : '';

    card.innerHTML = `
      <div class="deck-card__header">
        <span class="text-label deck-card__name">${DECK_LABELS[deckName] || deckName}</span>
        ${treatBadge}
      </div>
      <div class="deck-card__counts">
        <span class="c-active">ACT:${crew.active}</span>
        <span class="c-injured">INJ:${crew.injured}</span>
        <span class="c-critical">CRT:${crew.critical}</span>
        ${crew.dead > 0 ? `<span class="text-dim">KIA:${crew.dead}</span>` : ''}
      </div>
      <div class="deck-card__factor-row">
        <div class="gauge deck-card__factor-gauge">
          <div class="gauge__fill ${factorPct < 50 ? 'gauge__fill--danger' : factorPct < 75 ? 'gauge__fill--warn' : ''}"
               style="width:${factorPct}%"></div>
        </div>
        <span class="text-data">${factorPct}%</span>
      </div>
    `;
    // NOTE: click is handled via event delegation on deckListEl (see init()).
    deckListEl.appendChild(card);
  }
}

function renderTreatmentPanel() {
  if (!selectedDeck || !latestCrewData[selectedDeck]) {
    treatDeckLabelEl.textContent = 'No deck selected';
    treatmentNoneEl.style.display = '';
    treatmentActiveEl.style.display = 'none';
    return;
  }

  const crew = latestCrewData[selectedDeck];
  const treatment = activeTreatments[selectedDeck];

  treatDeckLabelEl.textContent = DECK_LABELS[selectedDeck] || selectedDeck;
  treatmentNoneEl.style.display = 'none';
  treatmentActiveEl.style.display = '';

  trActiveEl.textContent   = crew.active;
  trInjuredEl.textContent  = crew.injured;
  trCriticalEl.textContent = crew.critical;
  trDeadEl.textContent     = crew.dead;

  if (treatment) {
    trStatusEl.textContent = `TREATING ${treatment.toUpperCase()}`;
    trStatusEl.className = `text-data treatment-status--active`;
  } else {
    trStatusEl.textContent = 'IDLE';
    trStatusEl.className = 'text-data text-dim';
  }

  const hasSupplies = medicalSupplies >= 2;
  btnTreatInjuredEl.disabled = crew.injured === 0 || !hasSupplies;
  btnTreatCritEl.disabled    = crew.critical === 0 || !hasSupplies;
  btnCancelEl.disabled       = !treatment;
}

function renderDiseasePanel() {
  if (!diseaseListEl) return;
  const infected = diseaseState.infected_decks || {};
  const decks = Object.keys(infected);
  if (decks.length === 0) {
    diseaseListEl.innerHTML = '<span class="disease-clean text-dim label-sm">CLEAN — no outbreaks detected</span>';
    return;
  }
  diseaseListEl.innerHTML = decks.map(deck =>
    `<div class="disease-deck-row">
      <span class="disease-deck-name">${deck}</span>
      <span class="disease-pathogen">${infected[deck]}</span>
    </div>`
  ).join('');
}

function render() {
  renderSupplies();
  renderDeckList();
  renderTreatmentPanel();
  renderDiseasePanel();
}

// ---------------------------------------------------------------------------
// Interaction
// ---------------------------------------------------------------------------

function selectDeck(deckName) {
  selectedDeck = (selectedDeck === deckName) ? null : deckName;
  render();
}

btnTreatInjuredEl.addEventListener('click', () => {
  if (!selectedDeck) return;
  send('medical.treat_crew', { deck: selectedDeck, injury_type: 'injured' });
});

btnTreatCritEl.addEventListener('click', () => {
  if (!selectedDeck) return;
  send('medical.treat_crew', { deck: selectedDeck, injury_type: 'critical' });
});

btnCancelEl.addEventListener('click', () => {
  if (!selectedDeck) return;
  send('medical.cancel_treatment', { deck: selectedDeck });
});

// ---------------------------------------------------------------------------
// WebSocket message handlers
// ---------------------------------------------------------------------------

function handleShipState(payload) {
  if (payload.crew)              latestCrewData   = payload.crew;
  if (payload.active_treatments) activeTreatments = payload.active_treatments;
  if (payload.medical_supplies !== undefined) medicalSupplies = payload.medical_supplies;
  render();
}

function handleGameStarted(payload) {
  standbyEl.style.display = 'none';
  medicalMainEl.style.display = '';
  if (payload.mission_name) missionLabelEl.textContent = payload.mission_name;
  showBriefing(payload.mission_name, payload.briefing_text);
}

function handleDiseaseState(payload) {
  diseaseState = payload;
  renderDiseasePanel();
}

function handleHullHit() {
  SoundBank.play('hull_hit');
  stationEl.classList.add('hit');
  setTimeout(() => stationEl.classList.remove('hit'), HIT_FLASH_MS);
}

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  // Delegated click on the deck list — survives DOM rebuilds at 10 Hz.
  // Per-card addEventListener would be lost whenever innerHTML is replaced.
  deckListEl.addEventListener('click', (e) => {
    const card = e.target.closest('.deck-card');
    if (card && card.dataset.deck) selectDeck(card.dataset.deck);
  });

  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();
  });

  on('game.started',          handleGameStarted);
  on('ship.state',            handleShipState);
  on('ship.alert_changed',    (p) => setAlertLevel(p.level));
  on('ship.hull_hit',         handleHullHit);
  on('game.over',             (p) => { SoundBank.play(p.result === 'victory' ? 'victory' : 'defeat'); showGameOver(p.result, p.stats); });
  on('medical.disease_state', handleDiseaseState);

  initPuzzleRenderer(send);

  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();
  initNotifications(send, 'medical');
  initRoleBar(send, 'medical');

  on('lobby.welcome', () => {
    const name = sessionStorage.getItem('player_name') || 'MEDIC';
    send('lobby.claim_role', { role: 'medical', player_name: name });
  });

  connect();
}

document.addEventListener('DOMContentLoaded', init);
