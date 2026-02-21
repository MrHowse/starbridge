/**
 * Starbridge — Login Page (v0.04g)
 *
 * Allows a player to enter their callsign, which creates or loads their
 * profile from the server.  Profile summary and achievements are shown
 * before redirecting to the lobby.
 */

const ACHIEVEMENT_LABELS = {
  first_command:  'First Command',
  bridge_regular: 'Bridge Regular',
  veteran:        'Veteran',
  sharpshooter:   'Sharpshooter',
  life_saver:     'Life Saver',
  explorer:       'Explorer',
};

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const callsignInput   = document.getElementById('callsign-input');
const enterBtn        = document.getElementById('enter-btn');
const loginStatus     = document.getElementById('login-status');
const profileCard     = document.getElementById('profile-card');
const profileName     = document.getElementById('profile-name');
const statPlayed      = document.getElementById('stat-played');
const statWon         = document.getElementById('stat-won');
const statAch         = document.getElementById('stat-ach');
const achievementList = document.getElementById('achievement-list');
const leaderboardBtn  = document.getElementById('leaderboard-btn');
const lbModal         = document.getElementById('leaderboard-modal');
const lbClose         = document.getElementById('lb-close');
const lbContent       = document.getElementById('lb-content');

// ---------------------------------------------------------------------------
// Login flow
// ---------------------------------------------------------------------------

async function login() {
  const name = callsignInput.value.trim();
  if (!name) {
    callsignInput.focus();
    callsignInput.classList.add('lobby-input--error');
    setTimeout(() => callsignInput.classList.remove('lobby-input--error'), 1500);
    return;
  }

  enterBtn.disabled = true;
  loginStatus.textContent = 'Identifying…';

  try {
    const r = await fetch('/profiles/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });

    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      loginStatus.textContent = `Error: ${err.detail || r.statusText}`;
      enterBtn.disabled = false;
      return;
    }

    const profile = await r.json();
    _storeProfile(profile);
    _showProfileCard(profile);

    loginStatus.textContent = profile.games_played === 0
      ? 'Welcome, new crew member!'
      : `Welcome back, ${profile.name}!`;

    // Redirect after brief pause so the player can see their profile.
    setTimeout(() => { window.location.href = '/client/lobby/'; }, 1200);

  } catch (err) {
    loginStatus.textContent = `Network error: ${err.message}`;
    enterBtn.disabled = false;
  }
}

function _storeProfile(profile) {
  try {
    sessionStorage.setItem('player_profile', JSON.stringify(profile));
    sessionStorage.setItem('player_name', profile.name);
  } catch (_) { /* storage full — ignore */ }
}

function _showProfileCard(profile) {
  profileName.textContent = profile.name;
  statPlayed.textContent  = profile.games_played ?? 0;
  statWon.textContent     = profile.games_won ?? 0;
  statAch.textContent     = (profile.achievements ?? []).length;

  achievementList.innerHTML = '';
  for (const ach of (profile.achievements ?? [])) {
    const badge = document.createElement('span');
    badge.className = 'login-achievement-badge';
    badge.textContent = ACHIEVEMENT_LABELS[ach] || ach;
    achievementList.appendChild(badge);
  }

  profileCard.style.display = '';
}

// ---------------------------------------------------------------------------
// Leaderboard modal
// ---------------------------------------------------------------------------

async function openLeaderboard() {
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
    table.innerHTML = `
      <thead>
        <tr>
          <th class="lb-rank">#</th>
          <th>CALLSIGN</th>
          <th>WINS</th>
          <th>PLAYED</th>
          <th>ACHIEVEMENTS</th>
        </tr>
      </thead>
    `;
    const tbody = document.createElement('tbody');
    profiles.forEach((p, i) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="lb-rank">${i + 1}</td>
        <td>${_esc(p.name)}</td>
        <td>${p.games_won}</td>
        <td>${p.games_played}</td>
        <td>${(p.achievements || []).length}</td>
      `;
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    lbContent.innerHTML = '';
    lbContent.appendChild(table);
  } catch (err) {
    lbContent.innerHTML = `<span class="text-dim">Error: ${_esc(err.message)}</span>`;
  }
}

function _esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ---------------------------------------------------------------------------
// Event wiring
// ---------------------------------------------------------------------------

enterBtn.addEventListener('click', login);
callsignInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') login();
});

leaderboardBtn.addEventListener('click', openLeaderboard);
lbClose.addEventListener('click', () => { lbModal.style.display = 'none'; });
lbModal.addEventListener('click', (e) => {
  if (e.target === lbModal) lbModal.style.display = 'none';
});

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  // Pre-fill callsign if returning from lobby/station.
  const stored = sessionStorage.getItem('player_name');
  if (stored) callsignInput.value = stored;

  callsignInput.focus();
});
