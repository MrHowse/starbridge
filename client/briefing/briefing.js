/**
 * Starbridge — Mission Briefing Room
 *
 * Reads the game.started payload from sessionStorage, populates mission info,
 * animates a star field, and manages the pre-launch countdown.
 * The captain can override with "LAUNCH NOW"; all players receive
 * game.all_ready and navigate to their stations together.
 */

import { on, send, connect } from '../shared/connection.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const COUNTDOWN_SECONDS = 30;

const ROLE_URLS = {
  captain:            '/client/captain/',
  helm:               '/client/helm/',
  weapons:            '/client/weapons/',
  engineering:        '/client/engineering/',
  science:            '/client/science/',
  medical:            '/client/medical/',
  security:           '/client/security/',
  comms:              '/client/comms/',
  flight_ops:         '/client/flight_ops/',
  electronic_warfare: '/client/ew/',
  operations:         '/client/operations/',
  hazard_control:     '/client/hazard_control/',
  janitor:            '/client/janitor/',
};

const ROLE_LABELS = {
  captain:            'CAPTAIN',
  helm:               'HELM',
  weapons:            'WEAPONS',
  engineering:        'ENGINEERING',
  science:            'SCIENCE',
  medical:            'MEDICAL',
  security:           'SECURITY',
  comms:              'COMMS',
  flight_ops:         'FLIGHT OPS',
  electronic_warfare: 'ELECTRONIC WARFARE',
  operations:         'OPERATIONS',
  hazard_control:     'HAZARD CONTROL',
  janitor:            'JANITOR',
};

const CORE_ROLES = ['captain', 'helm', 'weapons', 'engineering', 'science', 'medical'];

const DIFFICULTY_LABELS = {
  cadet:     'CADET',
  officer:   'OFFICER',
  commander: 'COMMANDER',
  captain:   'CAPTAIN',
};

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let myRole           = null;
let payload          = null;
let countdown        = COUNTDOWN_SECONDS;
let countdownTimerId = null;
let navigated        = false;

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const missionTitleEl   = document.getElementById('mission-title');
const shipNameEl       = document.getElementById('ship-name');
const shipClassNameEl  = document.getElementById('ship-class-name');
const difficultyNameEl = document.getElementById('difficulty-name');
const briefingTextEl   = document.getElementById('briefing-text');
const crewRosterEl     = document.getElementById('crew-roster');
const shipStatsEl      = document.getElementById('ship-stats');
const countdownNumEl   = document.getElementById('countdown-num');
const readyBtnEl       = document.getElementById('ready-btn');
const launchBtnEl      = document.getElementById('launch-btn');
const readyStatusEl    = document.getElementById('ready-status');
const starChartEl      = document.getElementById('star-chart');

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);

function init() {
  myRole = sessionStorage.getItem('my_role');
  const raw = sessionStorage.getItem('game_started_payload');

  if (!raw) {
    window.location.href = '/client/lobby/';
    return;
  }

  try {
    payload = JSON.parse(raw);
  } catch (_) {
    window.location.href = '/client/lobby/';
    return;
  }

  populateMissionInfo();
  populateRoster();
  populateShipStats();

  // Captain gets the early-launch override button
  if (myRole === 'captain') {
    launchBtnEl.style.display = '';
  }

  initStarField();
  startCountdown();
  createWipeOverlay();

  readyBtnEl.addEventListener('click', onReadyClick);
  launchBtnEl.addEventListener('click', onLaunchClick);

  on('lobby.welcome', onWelcome);
  on('game.all_ready', onAllReady);
  connect();
}

// ---------------------------------------------------------------------------
// WebSocket handlers
// ---------------------------------------------------------------------------

function onWelcome() {
  // Re-claim role so this connection is properly registered and will
  // receive broadcasts (and, for captain, can send game.briefing_launch).
  const playerName = sessionStorage.getItem('player_name');
  if (myRole && playerName) {
    send('lobby.claim_role', { role: myRole, player_name: playerName });
  }
}

function onAllReady() {
  clearInterval(countdownTimerId);
  navigateToStation();
}

// ---------------------------------------------------------------------------
// Button handlers
// ---------------------------------------------------------------------------

function onReadyClick() {
  readyBtnEl.disabled = true;
  readyBtnEl.textContent = 'READY ✓';
  readyStatusEl.textContent = 'STANDING BY FOR LAUNCH…';
}

function onLaunchClick() {
  send('game.briefing_launch', {});
  launchBtnEl.disabled = true;
  readyStatusEl.textContent = 'LAUNCHING ALL HANDS…';
}

// ---------------------------------------------------------------------------
// Population helpers
// ---------------------------------------------------------------------------

function getShipClass() {
  if (!payload.ship_classes || !payload.ship_class) return null;
  return payload.ship_classes.find(sc => sc.id === payload.ship_class) ?? null;
}

function populateMissionInfo() {
  missionTitleEl.textContent = (payload.mission_name || 'UNKNOWN MISSION').toUpperCase();
  briefingTextEl.textContent = payload.briefing_text || '';

  const sc   = getShipClass();
  const diff = payload.difficulty || 'officer';

  shipNameEl.textContent      = payload.ship_class ? payload.ship_class.toUpperCase() : '—';
  shipClassNameEl.textContent = sc ? sc.name.toUpperCase() : (payload.ship_class || '—').toUpperCase();
  difficultyNameEl.textContent = DIFFICULTY_LABELS[diff] ?? diff.toUpperCase();
}

function populateRoster() {
  const players = payload.players || {};
  crewRosterEl.innerHTML = '';

  for (const role of [...CORE_ROLES, 'security', 'comms']) {
    const name = players[role];
    // Skip optional roles that have no occupant
    if (!name && !CORE_ROLES.includes(role)) continue;

    const row = document.createElement('div');
    row.className = 'briefing-roster-row';

    const roleEl = document.createElement('span');
    roleEl.className = 'briefing-roster__role';
    roleEl.textContent = ROLE_LABELS[role] ?? role.toUpperCase();

    const nameEl = document.createElement('span');
    if (name) {
      nameEl.className = 'briefing-roster__player';
      nameEl.textContent = name;
    } else {
      nameEl.className = 'briefing-roster__player briefing-roster__player--open';
      nameEl.textContent = 'OPEN';
    }

    row.appendChild(roleEl);
    row.appendChild(nameEl);
    crewRosterEl.appendChild(row);
  }
}

function populateShipStats() {
  const sc = getShipClass();
  if (!sc) {
    shipStatsEl.innerHTML = '';
    return;
  }

  const stats = [
    ['HULL POINTS', String(sc.max_hull)],
    ['TORPEDOES',   `${sc.torpedo_ammo} RDS`],
    ['DESIGNATION', sc.id.toUpperCase()],
    ['PROFILE',     sc.description || '—'],
  ];

  shipStatsEl.innerHTML = '';
  for (const [label, value] of stats) {
    const div      = document.createElement('div');
    div.className  = 'briefing-stat';

    const labelEl  = document.createElement('span');
    labelEl.className = 'briefing-stat__label';
    labelEl.textContent = label;

    const valueEl  = document.createElement('span');
    valueEl.className = 'briefing-stat__value';
    valueEl.textContent = value;

    div.appendChild(labelEl);
    div.appendChild(valueEl);
    shipStatsEl.appendChild(div);
  }
}

// ---------------------------------------------------------------------------
// Star field
// ---------------------------------------------------------------------------

let starCtx   = null;
let stars     = [];
let starRafId = null;

function initStarField() {
  starCtx = starChartEl.getContext('2d');
  resizeCanvas();
  window.addEventListener('resize', resizeCanvas);
  requestAnimationFrame(renderStars);
}

function resizeCanvas() {
  starChartEl.width  = starChartEl.offsetWidth  || 600;
  starChartEl.height = starChartEl.offsetHeight || 400;
  buildStars();
}

function buildStars() {
  const w = starChartEl.width;
  const h = starChartEl.height;
  const n = Math.floor((w * h) / 900);
  stars = Array.from({ length: n }, () => ({
    x:     Math.random() * w,
    y:     Math.random() * h,
    r:     Math.random() * 1.3 + 0.2,
    phase: Math.random() * Math.PI * 2,
    speed: Math.random() * 0.6 + 0.2,
  }));
}

function renderStars(now) {
  if (!starCtx) return;
  const w = starChartEl.width;
  const h = starChartEl.height;
  const t = now * 0.001;

  starCtx.fillStyle = '#050505';
  starCtx.fillRect(0, 0, w, h);

  for (const s of stars) {
    const alpha = 0.25 + 0.65 * (0.5 + 0.5 * Math.sin(s.phase + t * s.speed));
    starCtx.beginPath();
    starCtx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
    starCtx.fillStyle = `rgba(255,255,255,${alpha.toFixed(2)})`;
    starCtx.fill();
  }

  starRafId = requestAnimationFrame(renderStars);
}

// ---------------------------------------------------------------------------
// Countdown
// ---------------------------------------------------------------------------

function startCountdown() {
  countdownNumEl.textContent = countdown;
  countdownTimerId = setInterval(() => {
    countdown -= 1;
    countdownNumEl.textContent = countdown;
    if (countdown <= 0) {
      clearInterval(countdownTimerId);
      navigateToStation();
    }
  }, 1000);
}

// ---------------------------------------------------------------------------
// Navigation + screen wipe
// ---------------------------------------------------------------------------

let wipeEl = null;

function createWipeOverlay() {
  wipeEl = document.createElement('div');
  wipeEl.className = 'briefing-wipe';
  document.body.appendChild(wipeEl);
}

function navigateToStation() {
  if (navigated) return;
  navigated = true;

  if (starRafId) cancelAnimationFrame(starRafId);
  if (wipeEl) wipeEl.classList.add('briefing-wipe--active');

  const dest = (myRole && ROLE_URLS[myRole]) ? ROLE_URLS[myRole] : '/client/lobby/';
  // 650 ms — matches CSS transition (0.6 s) with a small buffer
  setTimeout(() => { window.location.href = dest; }, 650);
}
