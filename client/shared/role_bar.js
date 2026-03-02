/**
 * Starbridge — Persistent Role Bar
 *
 * Renders a fixed bottom strip showing all station roles and who's at each.
 * Appears on every station after game.started. Allows quick-switching to an
 * unoccupied station by clicking its slot.
 *
 * Usage:
 *   import { initRoleBar } from '../shared/role_bar.js';
 *   // In init(), after connect():
 *   initRoleBar(send, 'helm');
 *
 * On game.started, builds the bar from payload.players.
 * Click on an open role slot → navigates to that station URL.
 * The destination station page auto-claims the role on connect.
 */

import { on } from './connection.js';

// ---------------------------------------------------------------------------
// Station navigation map (role → client URL path)
// ---------------------------------------------------------------------------

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
  damage_control:     '/client/damage_control/',
  quartermaster:      '/client/quartermaster/',
};

const ROLE_LABELS = {
  captain:            'CAPT',
  helm:               'HELM',
  weapons:            'WPN',
  engineering:        'ENG',
  science:            'SCI',
  medical:            'MED',
  security:           'SEC',
  comms:              'COM',
  flight_ops:         'FLT',
  electronic_warfare: 'EW',
  operations:         'OPS',
  damage_control:     'DC',
  quartermaster:      'QM',
};

// Janitor names that unlock the secret station.
const _JANITOR_NAMES = ['the janitor', 'thejanitor'];

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _currentRole = null;
let _barEl       = null;
let _initialised = false;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Initialise the role bar for this station.
 * Safe to call multiple times — only the first call takes effect.
 *
 * @param {function} send        - WebSocket send helper (unused currently, future use)
 * @param {string}   currentRole - This station's own role (e.g. 'helm')
 */
export function initRoleBar(send, currentRole) {
  _currentRole = currentRole;

  if (_initialised) return;
  _initialised = true;

  _injectCSS();
  _buildBar();

  on('game.started', (payload) => {
    // Persist our own player name so isMyRole detection works across navigations.
    const name = (payload.players || {})[_currentRole];
    if (name) sessionStorage.setItem('player_name', name);
    _renderBar(payload.players || {});
  });

  // lobby.state is broadcast to all connections (including in-game stations)
  // whenever any role is claimed or released.  Use it to keep the bar live.
  on('lobby.state', (payload) => {
    if (!_barEl) return; // bar not yet built (game not started)
    _renderBar(_playersFromRoles(payload.roles || {}));
  });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Convert lobby.state roles dict → players dict suitable for _renderBar.
 * lobby.state uses 'DISCONNECTED:<name>' for reserved roles; strip the prefix
 * so the player can still be detected as isMyRole and click back.
 */
function _playersFromRoles(roles) {
  const players = {};
  for (const [role, val] of Object.entries(roles)) {
    if (!val) {
      players[role] = null;
    } else if (val.startsWith('DISCONNECTED:')) {
      players[role] = val.slice('DISCONNECTED:'.length);
    } else {
      players[role] = val;
    }
  }
  return players;
}

// ---------------------------------------------------------------------------
// DOM construction
// ---------------------------------------------------------------------------

function _buildBar() {
  _barEl = document.createElement('div');
  _barEl.className = 'role-bar';
  _barEl.setAttribute('aria-label', 'Station roles');
  document.body.appendChild(_barEl);
}

function _renderBar(players) {
  if (!_barEl) return;
  _barEl.innerHTML = '';

  const label = document.createElement('span');
  label.className = 'role-bar__title';
  label.textContent = 'STATIONS';
  _barEl.appendChild(label);

  // Identify own claimed roles so we can click back to them.
  const myName = sessionStorage.getItem('player_name') || '';

  for (const [role, url] of Object.entries(ROLE_URLS)) {
    const playerName = players[role] || null;
    const isSelf     = role === _currentRole;
    const isOpen     = playerName === null;
    // True if the current player is at this role on a different page.
    const isMyRole   = !isSelf && myName && playerName === myName;

    const pill = document.createElement('div');
    pill.className = [
      'role-bar__pill',
      isSelf    ? 'role-bar__pill--self'     : '',
      isMyRole  ? 'role-bar__pill--mine'     : '',
      isOpen    ? 'role-bar__pill--open'     : 'role-bar__pill--occupied',
    ].join(' ').trim();

    pill.setAttribute('title',
      isSelf   ? `You are here — ${role}` :
      isMyRole ? `Return to ${role}` :
      isOpen   ? `Switch to ${role}` :
                 `${playerName} — ${role}`
    );

    pill.innerHTML =
      `<span class="role-bar__pill-role">${ROLE_LABELS[role] || role.toUpperCase()}</span>` +
      `<span class="role-bar__pill-player">${_esc(playerName || '—')}</span>`;

    // Open slots and own roles on other pages are clickable.
    if (!isSelf && (isOpen || isMyRole) && url) {
      pill.classList.add('role-bar__pill--clickable');
      pill.addEventListener('click', () => {
        window.location.href = url;
      });
    }

    _barEl.appendChild(pill);
  }

  // Dynamically add janitor pill for janitor players only.
  if (_JANITOR_NAMES.includes(myName.toLowerCase())) {
    const jRole = 'janitor';
    const jUrl  = '/client/janitor/';
    const jName = players[jRole] || null;
    const jSelf = _currentRole === jRole;

    const jPill = document.createElement('div');
    jPill.className = [
      'role-bar__pill',
      jSelf ? 'role-bar__pill--self' : '',
      jName === null ? 'role-bar__pill--open' : 'role-bar__pill--occupied',
    ].join(' ').trim();
    jPill.setAttribute('title', jSelf ? 'You are here — janitor' : 'Janitorial Supplies');
    jPill.innerHTML =
      `<span class="role-bar__pill-role" style="color:#8a7a60">JAN</span>` +
      `<span class="role-bar__pill-player">${_esc(jName || '\u2014')}</span>`;

    if (!jSelf) {
      jPill.classList.add('role-bar__pill--clickable');
      jPill.addEventListener('click', () => { window.location.href = jUrl; });
    }
    _barEl.appendChild(jPill);
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ---------------------------------------------------------------------------
// Injected CSS
// ---------------------------------------------------------------------------

function _injectCSS() {
  if (document.getElementById('role-bar-styles')) return;
  const style = document.createElement('style');
  style.id = 'role-bar-styles';
  style.textContent = `
/* ── Role bar ── */

.role-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 700;
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.2rem 0.6rem;
  background: rgba(8, 8, 8, 0.95);
  border-top: 1px solid rgba(0, 255, 65, 0.15);
  font-family: "Share Tech Mono", monospace;
  font-size: 0.8rem;
  letter-spacing: 0.08em;
  height: 2rem;
  box-sizing: border-box;
}

.role-bar__title {
  color: rgba(0, 255, 65, 0.35);
  margin-right: 0.3rem;
  flex-shrink: 0;
}

.role-bar__pill {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0 0.45rem;
  border: 1px solid rgba(255, 255, 255, 0.08);
  line-height: 1.1;
  min-width: 44px;
  border-radius: 1px;
}

.role-bar__pill-role {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.3);
}

.role-bar__pill-player {
  font-size: 0.8rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 64px;
}

/* Current station */
.role-bar__pill--self {
  border-color: rgba(0, 255, 65, 0.5);
}
.role-bar__pill--self .role-bar__pill-role    { color: rgba(0, 255, 65, 0.6); }
.role-bar__pill--self .role-bar__pill-player  { color: #00ff41; }

/* Occupied by someone else */
.role-bar__pill--occupied .role-bar__pill-player { color: rgba(255, 255, 255, 0.55); }

/* Open slot */
.role-bar__pill--open .role-bar__pill-player { color: rgba(255, 255, 255, 0.2); }

/* Player's own role on another page */
.role-bar__pill--mine {
  border-color: rgba(0, 255, 65, 0.3);
}
.role-bar__pill--mine .role-bar__pill-player { color: rgba(0, 255, 65, 0.8); }

/* Open + clickable */
.role-bar__pill--clickable {
  cursor: pointer;
  transition: border-color 0.15s;
}
.role-bar__pill--clickable:hover {
  border-color: rgba(0, 255, 65, 0.4);
}
.role-bar__pill--clickable:hover .role-bar__pill-player {
  color: rgba(0, 255, 65, 0.7);
}
`;
  document.head.appendChild(style);
}
