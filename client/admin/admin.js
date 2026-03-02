/**
 * Starbridge — Admin Dashboard (v0.04h)
 *
 * Polls GET /admin/state every 3 seconds for live engagement monitoring
 * and ship snapshot.  Control actions use direct REST POST calls.
 */

// ---------------------------------------------------------------------------
// Station definitions
// ---------------------------------------------------------------------------

const STATIONS = [
  { role: 'captain',            label: 'CAPTAIN' },
  { role: 'helm',               label: 'HELM' },
  { role: 'weapons',            label: 'WEAPONS' },
  { role: 'engineering',        label: 'ENGINEERING' },
  { role: 'science',            label: 'SCIENCE' },
  { role: 'medical',            label: 'MEDICAL' },
  { role: 'security',           label: 'SECURITY' },
  { role: 'comms',              label: 'COMMS' },
  { role: 'flight_ops',         label: 'FLIGHT OPS' },
  { role: 'electronic_warfare', label: 'ELEC WARFARE' },
  { role: 'operations',         label: 'OPERATIONS' },
  { role: 'damage_control',     label: 'DAMAGE CTRL' },
];

// Per-station stat keys to show in mini-panels (derived from ship.systems).
const STATION_SYSTEM_MAP = {
  helm:               ['engines', 'manoeuvring'],
  weapons:            ['beams', 'torpedoes'],
  engineering:        ['engines', 'shields'],
  science:            ['sensors'],
  medical:            [],
  security:           [],
  comms:              [],
  flight_ops:         ['flight_deck'],
  electronic_warfare: ['ecm_suite'],
  operations:         [],
  damage_control:     [],
  captain:            [],
};

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const stationGrid   = document.getElementById('station-grid');
const gameStatus    = document.getElementById('game-status');
const tickCountEl   = document.getElementById('tick-count');
const pauseBtn      = document.getElementById('pause-btn');
const resumeBtn     = document.getElementById('resume-btn');
const broadcastInput = document.getElementById('broadcast-input');
const broadcastBtn  = document.getElementById('broadcast-btn');
const annotateRole  = document.getElementById('annotate-role');
const annotateInput = document.getElementById('annotate-input');
const annotateBtn   = document.getElementById('annotate-btn');
const diffSelect    = document.getElementById('difficulty-select');
const diffBtn       = document.getElementById('difficulty-btn');
const saveBtn       = document.getElementById('save-btn');
const saveStatus    = document.getElementById('save-status');
const adminLog      = document.getElementById('admin-log');
const shipHull      = document.getElementById('ship-hull');
const shipAlert     = document.getElementById('ship-alert');
const shipVel       = document.getElementById('ship-vel');
const shipHdg       = document.getElementById('ship-hdg');
const enemyCount    = document.getElementById('enemy-count');

// Cache of player names by role (updated from last lobby.state / game.started).
let _players = {};
let _isPaused = false;

// ---------------------------------------------------------------------------
// Build mini-panel DOM
// ---------------------------------------------------------------------------

function buildMiniPanels() {
  stationGrid.innerHTML = '';
  for (const { role, label } of STATIONS) {
    const panel = document.createElement('div');
    panel.className = 'admin-mini';
    panel.dataset.role = role;

    panel.innerHTML = `
      <div class="admin-mini__header">
        <span class="admin-mini__role">${label}</span>
        <span class="admin-mini__engagement admin-mini__engagement--offline"
              data-engagement="${role}"></span>
        <span class="admin-mini__player" data-player="${role}">VACANT</span>
      </div>
      <div class="admin-mini__stats" data-stats="${role}">
        <span class="admin-mini__stat text-dim" style="font-size:.55rem">—</span>
      </div>
      <div class="admin-mini__idle-label" data-idle-label="${role}" style="display:none"></div>
    `;
    stationGrid.appendChild(panel);
  }
}

// ---------------------------------------------------------------------------
// Update mini-panels from state response
// ---------------------------------------------------------------------------

function updatePanels(state) {
  const { engagement, ship, running, tick_count, paused } = state;
  _isPaused = paused;

  // Header
  gameStatus.textContent = !running ? 'NO GAME ACTIVE' : paused ? '⏸ PAUSED' : '● RUNNING';
  gameStatus.style.color = !running ? 'rgba(0,255,65,.4)' : paused ? '#ffb000' : '#00ff41';
  tickCountEl.textContent = running ? `TICK ${tick_count}` : '';

  // Control buttons — only enabled when the game state makes them meaningful.
  pauseBtn.disabled  = !running || paused;
  resumeBtn.disabled = !running || !paused;

  // Ship summary bar
  if (ship) {
    shipHull.textContent  = ship.hull ?? '—';
    shipAlert.textContent = (ship.alert_level || '—').toUpperCase();
    shipVel.textContent   = ship.velocity ?? '—';
    shipHdg.textContent   = ship.heading ?? '—';
    enemyCount.textContent = ship.enemy_count ?? '—';
  }

  // Mini-panels
  for (const { role } of STATIONS) {
    const eng   = engagement?.[role] ?? { status: 'offline', seconds_since_last_action: null };
    const dot   = document.querySelector(`[data-engagement="${role}"]`);
    const pname = document.querySelector(`[data-player="${role}"]`);
    const stats = document.querySelector(`[data-stats="${role}"]`);
    const idle  = document.querySelector(`[data-idle-label="${role}"]`);
    if (!dot) continue;

    // Engagement dot
    dot.className = `admin-mini__engagement admin-mini__engagement--${eng.status}`;

    // Player name
    if (pname) pname.textContent = _players[role] || 'VACANT';

    // Idle warning
    if (idle) {
      if (eng.status === 'idle') {
        idle.textContent = `IDLE ${Math.floor(eng.seconds_since_last_action ?? 0)}s`;
        idle.className = 'admin-mini__idle-label';
        idle.style.display = '';
      } else if (eng.status === 'away') {
        idle.textContent = `AWAY ${Math.floor(eng.seconds_since_last_action ?? 0)}s`;
        idle.className = 'admin-mini__idle-label admin-mini__idle-label--away';
        idle.style.display = '';
      } else {
        idle.style.display = 'none';
      }
    }

    // System stats from ship.systems
    if (stats && ship?.systems) {
      const sysList = STATION_SYSTEM_MAP[role] || [];
      if (sysList.length > 0) {
        stats.innerHTML = sysList
          .filter(s => ship.systems[s])
          .map(s => {
            const sys = ship.systems[s];
            return `<div class="admin-mini__stat">
              <span>${s.toUpperCase()}</span>
              <span class="admin-mini__stat-value">${sys.power}W / ${sys.health}HP</span>
            </div>`;
          })
          .join('');
      } else {
        stats.innerHTML = '<span class="admin-mini__stat text-dim">—</span>';
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------

let _pollTimer = null;

async function poll() {
  try {
    const r = await fetch('/admin/state');
    if (r.ok) {
      const state = await r.json();
      updatePanels(state);
    }
  } catch (_) { /* server offline */ }
}

function startPolling() {
  poll(); // immediate first call
  _pollTimer = setInterval(poll, 3000);
}

// ---------------------------------------------------------------------------
// Control actions
// ---------------------------------------------------------------------------

async function _post(url, body = {}) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return r;
}

function _log(text) {
  const entry = document.createElement('div');
  entry.className = 'admin-log-entry';
  const ts = new Date().toTimeString().slice(0, 8);
  entry.textContent = `[${ts}] ${text}`;
  adminLog.appendChild(entry);
  adminLog.scrollTop = adminLog.scrollHeight;
}

pauseBtn.addEventListener('click', async () => {
  try {
    const r = await _post('/admin/pause');
    if (r.ok) {
      _log('Game paused.');
      poll();
    } else {
      const err = await r.json().catch(() => ({}));
      _log(`Pause error: ${err.detail || r.statusText}`);
    }
  } catch (e) { _log(`Error: ${e.message}`); }
});

resumeBtn.addEventListener('click', async () => {
  try {
    const r = await _post('/admin/resume');
    if (r.ok) {
      _log('Game resumed.');
      poll();
    } else {
      const err = await r.json().catch(() => ({}));
      _log(`Resume error: ${err.detail || r.statusText}`);
    }
  } catch (e) { _log(`Error: ${e.message}`); }
});

broadcastBtn.addEventListener('click', async () => {
  const msg = broadcastInput.value.trim();
  if (!msg) return;
  try {
    const r = await _post('/admin/broadcast', { message: msg });
    if (r.ok) {
      _log(`Broadcast: "${msg}"`);
      broadcastInput.value = '';
    } else {
      const err = await r.json().catch(() => ({}));
      _log(`Broadcast error: ${err.detail || r.statusText}`);
    }
  } catch (e) { _log(`Error: ${e.message}`); }
});

annotateBtn.addEventListener('click', async () => {
  const role = annotateRole.value;
  const msg  = annotateInput.value.trim();
  if (!role || !msg) {
    _log('Select a station and enter a message.');
    return;
  }
  try {
    const r = await _post('/admin/annotate', { role, message: msg });
    if (r.ok) {
      _log(`Note sent to ${role}: "${msg}"`);
      annotateInput.value = '';
    } else {
      const err = await r.json().catch(() => ({}));
      _log(`Annotate error: ${err.detail || r.statusText}`);
    }
  } catch (e) { _log(`Error: ${e.message}`); }
});

diffBtn.addEventListener('click', async () => {
  const preset = diffSelect.value;
  try {
    const r = await _post('/admin/difficulty', { preset });
    if (r.ok) {
      _log(`Difficulty set to ${preset}.`);
    } else {
      const err = await r.json().catch(() => ({}));
      _log(`Difficulty error: ${err.detail || r.statusText}`);
    }
  } catch (e) { _log(`Error: ${e.message}`); }
});

saveBtn.addEventListener('click', async () => {
  saveBtn.disabled = true;
  saveStatus.textContent = 'Saving…';
  try {
    const r = await _post('/admin/save');
    if (r.ok) {
      const { save_id } = await r.json();
      saveStatus.textContent = `Saved: ${save_id}`;
      _log(`Game saved: ${save_id}`);
    } else {
      const err = await r.json().catch(() => ({}));
      saveStatus.textContent = `Error: ${err.detail || r.statusText}`;
      _log(`Save error: ${err.detail || r.statusText}`);
    }
  } catch (e) {
    saveStatus.textContent = `Error: ${e.message}`;
    _log(`Error: ${e.message}`);
  }
  saveBtn.disabled = false;
  setTimeout(() => { saveStatus.textContent = ''; }, 5000);
});

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  buildMiniPanels();
  startPolling();
  _log('Admin dashboard connected.');

  // Restore player names from sessionStorage (set by lobby.js on game.started).
  try {
    const raw = sessionStorage.getItem('game_started_payload');
    if (raw) {
      const payload = JSON.parse(raw);
      _players = payload.players || {};
    }
  } catch (_) { /* ignore */ }
});
