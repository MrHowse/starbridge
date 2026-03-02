/**
 * Starbridge — Lobby Client
 *
 * Handles role selection, player list, and game launch.
 * Communicates with the server via the shared connection module.
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import { setStatusDot, redirectToStation } from '../shared/ui_components.js';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** @type {string|null} Server-assigned connection ID, received in lobby.welcome */
let myConnectionId = null;

/** @type {string|null} Role currently held by this client */
let myRole = null;

/** @type {Object} Latest roles dict from lobby.state, for launch-time crew count */
let _latestRoles = {};

const ROLES = [
  'captain', 'helm', 'weapons', 'engineering', 'science', 'medical',
  'security', 'comms', 'flight_ops', 'electronic_warfare', 'operations', 'hazard_control',
  'quartermaster',
];

/** Callsign names that unlock the secret janitor station. */
const JANITOR_NAMES = ['the janitor', 'thejanitor'];
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
  electronic_warfare: 'ELEC WARFARE',
  operations:         'OPERATIONS',
  hazard_control:     'HAZCON',
  quartermaster:      'QUARTERMASTER',
};

/** Minimum crew per ship class (matches ships/*.json min_crew field). */
const MIN_CREW = {
  scout:        3,
  corvette:     4,
  frigate:      6,
  cruiser:      8,
  battleship:  10,
  medical_ship: 5,
  carrier:      7,
};

/** Brief stat summary per class for the silhouette preview. */
const SHIP_STATS = {
  scout:        'HP 60 | SPD 250 | ARM 0 | SHLD 40',
  corvette:     'HP 90 | SPD 200 | ARM 5 | SHLD 60',
  frigate:      'HP 120 | SPD 160 | ARM 10 | SHLD 80',
  cruiser:      'HP 180 | SPD 120 | ARM 20 | SHLD 120',
  battleship:   'HP 300 | SPD 80 | ARM 40 | SHLD 200',
  carrier:      'HP 200 | SPD 100 | ARM 15 | SHLD 150',
  medical_ship: 'HP 100 | SPD 140 | ARM 5 | SHLD 70',
};

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusDotEl    = document.querySelector('[data-status-dot]');
const statusLabelEl  = document.querySelector('[data-status-label]');
const callsignInput  = document.querySelector('[data-callsign-input]');
const rolesGridEl    = document.querySelector('[data-roles-grid]');
const launchPanelEl  = document.querySelector('[data-launch-panel]');
const launchStatusEl = document.querySelector('[data-launch-status]');
const launchBtnEl       = document.querySelector('[data-launch-btn]');
const missionSelectEl   = document.querySelector('[data-mission-select]');
const sessionLabelEl    = document.querySelector('[data-session-label]');

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  buildRoleCards();
  _loadMissions();

  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();
  });

  on('lobby.welcome', handleWelcome);
  on('lobby.state',   handleLobbyState);
  on('lobby.error',   handleLobbyError);
  on('game.started',  handleGameStarted);
  on('lobby.janitor_available', handleJanitorAvailable);

  // Detect janitor name as the user types — show secret role card.
  callsignInput.addEventListener('input', () => {
    const name = callsignInput.value.trim().toLowerCase();
    if (JANITOR_NAMES.includes(name)) {
      handleJanitorAvailable();
    }
  });

  // Ship class silhouette preview.
  const shipClassEl  = document.querySelector('[data-ship-class-select]');
  const previewImg   = document.getElementById('ship-preview-img');
  const previewStats = document.getElementById('ship-preview-stats');
  function _updateShipPreview() {
    const cls = shipClassEl ? shipClassEl.value : 'frigate';
    if (previewImg) previewImg.src = `/client/shared/silhouettes/${cls}.svg`;
    if (previewStats) previewStats.textContent = SHIP_STATS[cls] || '';
  }
  if (shipClassEl) {
    shipClassEl.addEventListener('change', _updateShipPreview);
    _updateShipPreview();  // set initial preview
  }

  launchBtnEl.addEventListener('click', () => {
    const mission_id   = missionSelectEl ? missionSelectEl.value : 'sandbox';
    const difficultyEl = document.querySelector('[data-difficulty-select]');
    const difficulty   = difficultyEl ? difficultyEl.value : 'officer';
    const shipClassEl  = document.querySelector('[data-ship-class-select]');
    const ship_class   = shipClassEl ? shipClassEl.value : 'frigate';

    // Soft min-crew warning — warn but do not block launch.
    const minCrew     = MIN_CREW[ship_class] || 1;
    const claimedCount = Object.values(_latestRoles)
      .filter(v => v !== null && !String(v).startsWith('DISCONNECTED:')).length;
    if (claimedCount < minCrew) {
      launchStatusEl.textContent =
        `⚠ WARNING: ${ship_class.toUpperCase()} requires ${minCrew} crew (${claimedCount} ready). Launch anyway?`;
      launchStatusEl.style.color = 'var(--warning, #ffaa00)';
      // Allow a second click to actually launch.
      launchBtnEl.dataset.warned = '1';
      if (!launchBtnEl.dataset.confirmed) {
        launchBtnEl.dataset.confirmed = '1';
        return;
      }
    }
    // Clear warning state.
    launchBtnEl.dataset.confirmed = '';
    launchStatusEl.style.color = '';

    send('lobby.start_game', { mission_id, difficulty, ship_class });
  });

  connect();
}

// ---------------------------------------------------------------------------
// Role card DOM construction
// ---------------------------------------------------------------------------

function buildRoleCards() {
  for (const role of ROLES) {
    const card = document.createElement('div');
    card.className = 'role-card panel';
    card.dataset.roleCard = role;

    card.innerHTML = `
      <div class="panel__header role-card__header">
        <span class="text-header">${ROLE_LABELS[role]}</span>
      </div>
      <div class="role-card__body">
        <span class="role-card__occupant text-data" data-occupant="${role}">VACANT</span>
        <div class="role-card__actions">
          <button class="btn btn--primary role-card__claim" data-claim="${role}" aria-label="Claim ${ROLE_LABELS[role]}">CLAIM</button>
          <button class="btn role-card__release" data-release="${role}" aria-label="Release ${ROLE_LABELS[role]}">RELEASE</button>
        </div>
      </div>
    `;

    card.querySelector(`[data-claim="${role}"]`).addEventListener('click', () => claimRole(role));
    card.querySelector(`[data-release="${role}"]`).addEventListener('click', releaseRole);

    rolesGridEl.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function claimRole(role) {
  const callsign = callsignInput.value.trim();
  if (!callsign || callsign.length > 20) {
    callsignInput.focus();
    callsignInput.classList.add('lobby-input--error');
    setTimeout(() => callsignInput.classList.remove('lobby-input--error'), 1500);
    return;
  }
  send('lobby.claim_role', { role, player_name: callsign });
}

function releaseRole() {
  send('lobby.release_role', {});
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

/** @param {{ connection_id: string, is_host: boolean }} payload */
function handleWelcome(payload) {
  myConnectionId = payload.connection_id;
  updateLaunchPanel(payload.is_host);
}

/** @param {{ roles: Object, host: string, session_id: string }} payload */
function handleLobbyState(payload) {
  const { roles, host, session_id } = payload;
  _latestRoles = roles;

  sessionLabelEl.textContent = `SESSION ${session_id.slice(0, 8).toUpperCase()}`;

  const isHost = myConnectionId !== null && host === myConnectionId;
  updateLaunchPanel(isHost);

  // Determine which role belongs to this client by matching callsign.
  // This is intentionally simple for Phase 1 — works fine on a LAN where
  // callsign collisions are unlikely. Phase 2+ can use server-sent role info.
  const callsign = callsignInput.value.trim();
  myRole = null;

  for (const role of ROLES) {
    const rawValue    = roles[role];
    const occupantEl  = document.querySelector(`[data-occupant="${role}"]`);
    const claimBtn    = document.querySelector(`[data-claim="${role}"]`);
    const releaseBtn  = document.querySelector(`[data-release="${role}"]`);
    const card        = document.querySelector(`[data-role-card="${role}"]`);

    // Parse reserved-role sentinel: "DISCONNECTED:<player_name>"
    const isReserved  = typeof rawValue === 'string' && rawValue.startsWith('DISCONNECTED:');
    const playerName  = isReserved ? rawValue.slice('DISCONNECTED:'.length) : rawValue;

    if (isReserved) {
      occupantEl.textContent = `${playerName} [DC]`;
      card.classList.add('role-card--occupied');
      card.classList.add('role-card--disconnected');
    } else if (playerName) {
      occupantEl.textContent = playerName;
      card.classList.add('role-card--occupied');
      card.classList.remove('role-card--disconnected');
    } else {
      occupantEl.textContent = 'VACANT';
      card.classList.remove('role-card--occupied');
      card.classList.remove('role-card--disconnected');
    }

    const isMine = callsign && playerName === callsign;
    if (isMine) myRole = role;

    card.classList.toggle('role-card--mine', Boolean(isMine));
    // Allow reclaim if reserved for this player; block others from reserved roles.
    const blocked = playerName && !isMine;
    claimBtn.style.display  = (!blocked) ? '' : 'none';
    releaseBtn.style.display = (isMine && !isReserved) ? '' : 'none';
    claimBtn.disabled = Boolean(blocked);
  }

  // Janitor card is injected dynamically — detect claim via occupant element.
  const janitorOccupant = document.querySelector('[data-occupant="janitor"]');
  if (janitorOccupant && callsign) {
    const jName = janitorOccupant.textContent.trim();
    if (jName === callsign) myRole = 'janitor';
  }

  // Enable launch if host and at least one role is claimed (reserved don't count)
  const anyRoleClaimed = Object.values(roles).some(v => v !== null && !String(v).startsWith('DISCONNECTED:'))
    || (myRole === 'janitor');
  launchBtnEl.disabled = !(isHost && anyRoleClaimed);
}

/** @param {{ message: string }} payload */
function handleLobbyError(payload) {
  // Brief visual flash on the input to signal rejection
  callsignInput.classList.add('lobby-input--error');
  setTimeout(() => callsignInput.classList.remove('lobby-input--error'), 1500);
  console.warn('[lobby] Error:', payload.message);
}

/** Handle janitor role availability hint */
function handleJanitorAvailable() {
  // Only inject if not already present.
  if (document.querySelector('[data-role-card="janitor"]')) return;

  const card = document.createElement('div');
  card.className = 'role-card panel role-card--janitor';
  card.dataset.roleCard = 'janitor';
  card.innerHTML = `
    <div class="panel__header role-card__header" style="background:#5a4a3a;color:#e8d5b0">
      <span class="text-header">JANITORIAL SUPPLIES</span>
    </div>
    <div class="role-card__body">
      <span class="role-card__occupant text-data" data-occupant="janitor">VACANT</span>
      <div class="role-card__actions">
        <button class="btn btn--primary role-card__claim" data-claim="janitor" aria-label="Claim JANITOR" style="background:#5a4a3a;border-color:#8a7a60">CLAIM</button>
      </div>
    </div>
  `;

  card.querySelector('[data-claim="janitor"]').addEventListener('click', () => {
    const callsign = callsignInput.value.trim();
    if (!callsign) return;
    send('lobby.claim_role', { role: 'janitor', player_name: callsign });
    // Optimistically update card — janitor is excluded from lobby.state broadcasts.
    const occ = card.querySelector('[data-occupant="janitor"]');
    if (occ) occ.textContent = callsign;
    card.classList.add('role-card--occupied', 'role-card--mine');
    myRole = 'janitor';
    // Re-enable launch button if host.
    if (myConnectionId) launchBtnEl.disabled = false;
  });

  rolesGridEl.appendChild(card);
}

/** @param {{ mission_id: string, mission_name: string, briefing_text: string }} payload */
function handleGameStarted(payload) {
  console.log(`[lobby] Game started: ${payload.mission_name}`);
  // Persist callsign and role so station/briefing pages can re-claim on reconnect.
  const callsign = callsignInput.value.trim();
  if (callsign) sessionStorage.setItem('player_name', callsign);
  if (myRole)   sessionStorage.setItem('my_role', myRole);
  // Persist game payload so briefing page can display mission info.
  try {
    sessionStorage.setItem('game_started_payload', JSON.stringify(payload));
  } catch (_) { /* storage full — ignore */ }
  // Freeze all interactive controls before navigating away.
  document.querySelectorAll('.btn').forEach(btn => { btn.disabled = true; });
  launchStatusEl.textContent = `LAUNCHING — ${payload.mission_name.toUpperCase()}`;
  // Navigate to briefing room (which will then route to station after countdown).
  window.location.href = '/client/briefing/';
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

/** @param {boolean} isHost */
function updateLaunchPanel(isHost) {
  launchPanelEl.style.display = isHost ? '' : 'none';
  launchStatusEl.textContent  = isHost ? 'YOU ARE HOST — SELECT MISSION AND LAUNCH' : '';
  if (isHost) _loadSaves();
}

// ---------------------------------------------------------------------------
// Save / Resume
// ---------------------------------------------------------------------------

async function _loadSaves() {
  const resumeSection = document.getElementById('resume-section');
  const saveSelect    = document.getElementById('save-select');
  const resumeBtn     = document.getElementById('resume-btn');
  if (!resumeSection || !saveSelect || !resumeBtn) return;

  try {
    const r    = await fetch('/saves');
    const data = await r.json();
    const saves = data.saves || [];

    if (saves.length === 0) {
      resumeSection.style.display = 'none';
      return;
    }

    // Populate select, keeping the placeholder first option.
    saveSelect.innerHTML = '<option value="">SELECT SAVE…</option>';
    for (const s of saves) {
      const opt = document.createElement('option');
      opt.value = s.save_id;
      const ts = s.saved_at ? s.saved_at.replace('T', ' ') : '?';
      opt.textContent = `${s.mission_id} — ${s.ship_class} — ${ts}`;
      saveSelect.appendChild(opt);
    }

    resumeSection.style.display = '';

    saveSelect.addEventListener('change', () => {
      resumeBtn.disabled = !saveSelect.value;
    });

    resumeBtn.addEventListener('click', async () => {
      const saveId = saveSelect.value;
      if (!saveId) return;
      await _resumeGame(saveId);
    });
  } catch (_err) {
    // /saves unavailable — hide resume section.
    if (resumeSection) resumeSection.style.display = 'none';
  }
}

async function _resumeGame(saveId) {
  const resumeBtn    = document.getElementById('resume-btn');
  const resumeStatus = document.getElementById('resume-status');
  if (resumeBtn) resumeBtn.disabled = true;
  if (resumeStatus) resumeStatus.textContent = 'Resuming…';

  try {
    const r = await fetch(`/saves/resume/${encodeURIComponent(saveId)}`, { method: 'POST' });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      if (resumeStatus) resumeStatus.textContent = `Error: ${err.detail || r.statusText}`;
      if (resumeBtn) resumeBtn.disabled = false;
      return;
    }
    // game.started will be broadcast by the server; handleGameStarted() navigates.
    if (resumeStatus) resumeStatus.textContent = 'Restored — launching…';
  } catch (err) {
    if (resumeStatus) resumeStatus.textContent = `Network error: ${err.message}`;
    if (resumeBtn) resumeBtn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Mission list (dynamic)
// ---------------------------------------------------------------------------

async function _loadMissions() {
  if (!missionSelectEl) return;
  try {
    const r = await fetch('/editor/missions');
    const data = await r.json();
    const missions = data.missions || [];
    if (missions.length === 0) return;

    // Keep the default SANDBOX option, add the rest.
    // Group: regular missions first, then training.
    const regular  = missions.filter(m => m.id !== 'sandbox' && !m.id.startsWith('train_'));
    const training = missions.filter(m => m.id.startsWith('train_'));

    for (const m of regular) {
      const opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = (m.name || m.id).toUpperCase();
      missionSelectEl.appendChild(opt);
    }

    if (training.length > 0) {
      const group = document.createElement('optgroup');
      group.label = 'TRAINING';
      for (const m of training) {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = (m.name || m.id).toUpperCase();
        group.appendChild(opt);
      }
      missionSelectEl.appendChild(group);
    }
  } catch (_err) {
    // Fetch failed — keep the static SANDBOX fallback.
  }
}

// ---------------------------------------------------------------------------
// Player profile card + leaderboard (v0.04g)
// ---------------------------------------------------------------------------

function initProfileCard() {
  try {
    const raw = sessionStorage.getItem('player_profile');
    if (!raw) return;
    const profile = JSON.parse(raw);
    const footerProfile = document.getElementById('footer-profile');
    const footerName    = document.getElementById('footer-profile-name');
    const footerWins    = document.getElementById('footer-profile-wins');
    if (footerProfile && footerName && footerWins) {
      footerName.textContent = profile.name || '';
      footerWins.textContent = `${profile.games_won || 0}W / ${profile.games_played || 0}G`;
      footerProfile.style.display = '';
    }
  } catch (_) { /* ignore */ }
}

function initLeaderboard() {
  const lbBtn   = document.getElementById('leaderboard-btn');
  const lbModal = document.getElementById('leaderboard-modal');
  const lbClose = document.getElementById('lb-close');
  const lbContent = document.getElementById('lb-content');
  if (!lbBtn || !lbModal) return;

  lbBtn.addEventListener('click', async () => {
    lbModal.style.display = 'flex';
    lbContent.innerHTML = '<span class="text-dim">Loading…</span>';
    try {
      const r = await fetch('/profiles/leaderboard');
      const { profiles } = await r.json();
      if (!profiles || profiles.length === 0) {
        lbContent.innerHTML = '<span class="text-dim">No profiles yet.</span>';
        return;
      }
      const table = document.createElement('table');
      table.className = 'lb-table';
      table.innerHTML = `<thead><tr>
        <th class="lb-rank">#</th>
        <th>CALLSIGN</th><th>WINS</th><th>PLAYED</th><th>ACHIEVEMENTS</th>
      </tr></thead>`;
      const tbody = document.createElement('tbody');
      profiles.forEach((p, i) => {
        const tr = document.createElement('tr');
        const esc = (s) => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        tr.innerHTML = `<td class="lb-rank">${i+1}</td><td>${esc(p.name)}</td>
          <td>${p.games_won}</td><td>${p.games_played}</td>
          <td>${(p.achievements||[]).length}</td>`;
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      lbContent.innerHTML = '';
      lbContent.appendChild(table);
    } catch (err) {
      lbContent.innerHTML = `<span class="text-dim">Error loading leaderboard.</span>`;
    }
  });

  lbClose.addEventListener('click', () => { lbModal.style.display = 'none'; });
  lbModal.addEventListener('click', (e) => {
    if (e.target === lbModal) lbModal.style.display = 'none';
  });
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  init();
  initProfileCard();
  initLeaderboard();
});
