/**
 * Starbridge — Shared UI Helpers
 *
 * Reusable DOM utilities shared across all stations.
 */

/**
 * Set the alert level, swapping the --primary colour family on the root.
 * @param {'green'|'yellow'|'red'} level
 */
export function setAlertLevel(level) {
  const root = document.documentElement;
  root.style.setProperty('--primary',      `var(--alert-${level})`);
  root.style.setProperty('--primary-dim',  `var(--alert-${level}-dim)`);
  root.style.setProperty('--primary-glow', `var(--alert-${level}-glow)`);
}

/**
 * Update a .status-dot element to reflect the current connection state.
 * @param {HTMLElement} el
 * @param {'connected'|'reconnecting'|'disconnected'} status
 */
export function setStatusDot(el, status) {
  el.className = `status-dot status-dot--${status}`;
}

/**
 * Navigate to the station page for the given role.
 * Falls back to viewscreen if role is null/undefined.
 * @param {string|null} role
 */
export function redirectToStation(role) {
  const station = role || 'viewscreen';
  window.location.href = `/client/${station}/`;
}

// ---------------------------------------------------------------------------
// Briefing overlay
// ---------------------------------------------------------------------------

let _briefingTimer = null;

/**
 * Show a mission briefing overlay on top of the current station.
 * Auto-dismisses after 15 seconds. Click anywhere on the overlay to dismiss early.
 * @param {string} missionName
 * @param {string} briefingText
 */
export function showBriefing(missionName, briefingText) {
  // Skip for sandbox (no meaningful briefing) or if already shown this game session.
  if (!briefingText || missionName === 'Sandbox') return;
  const shownKey = 'starbridge_briefing_shown';
  if (sessionStorage.getItem(shownKey) === missionName) return;
  sessionStorage.setItem(shownKey, missionName);

  const container = document.querySelector('.station-container') || document.body;

  let el = document.querySelector('[data-briefing-overlay]');
  if (!el) {
    el = document.createElement('div');
    el.setAttribute('data-briefing-overlay', '');
    el.className = 'briefing-overlay';
    el.innerHTML = `
      <div class="briefing-box panel">
        <p class="text-label briefing-mission">MISSION BRIEFING</p>
        <p class="text-title briefing-title" data-briefing-title></p>
        <p class="text-body briefing-body" data-briefing-body></p>
        <p class="briefing-dismiss">Click to dismiss — auto-closes in 15s</p>
      </div>`;
    container.appendChild(el);
    el.addEventListener('click', () => dismissBriefing(el));
  }

  el.querySelector('[data-briefing-title]').textContent = missionName.toUpperCase();
  el.querySelector('[data-briefing-body]').textContent  = briefingText;
  el.style.display = 'flex';

  if (_briefingTimer) clearTimeout(_briefingTimer);
  _briefingTimer = setTimeout(() => dismissBriefing(el), 15_000);
}

function dismissBriefing(el) {
  if (_briefingTimer) { clearTimeout(_briefingTimer); _briefingTimer = null; }
  el.style.display = 'none';
}

// ---------------------------------------------------------------------------
// Shared game-over overlay
// ---------------------------------------------------------------------------

/**
 * Show a full-screen game-over overlay with result, stats, and Return to Lobby.
 * Reuses an existing [data-shared-game-over] element if present, otherwise
 * creates one. Captain station uses its own HTML-declared overlay instead.
 * @param {string} result  'victory' | 'defeat'
 * @param {{ duration_s?: number, hull_remaining?: number, debrief?: object, captain_log?: Array }} stats
 */
export function showGameOver(result, stats = {}) {
  const container = document.querySelector('.station-container') || document.body;

  // Save debrief payload to localStorage for the debrief page.
  try {
    localStorage.setItem('starbridge_debrief', JSON.stringify({
      result,
      duration_s:    stats.duration_s    ?? null,
      hull_remaining: stats.hull_remaining ?? null,
      captain_log:   stats.captain_log   ?? [],
      debrief:       stats.debrief       ?? null,
    }));
  } catch (_) { /* storage unavailable */ }

  let el = document.querySelector('[data-shared-game-over]');
  if (!el) {
    el = document.createElement('div');
    el.setAttribute('data-shared-game-over', '');
    el.className = 'shared-game-over';
    container.appendChild(el);
  }

  const title  = result === 'victory' ? 'MISSION COMPLETE' : 'SHIP DESTROYED';
  const dur    = stats.duration_s != null
    ? `${Math.floor(stats.duration_s / 60)}:${String(Math.round(stats.duration_s % 60)).padStart(2, '0')}`
    : '—';
  const hull   = stats.hull_remaining != null
    ? `${Math.round(stats.hull_remaining)}%`
    : '—';
  const hasDebrief = stats.debrief != null;

  el.innerHTML = `
    <div class="game-over-box panel">
      <p class="text-title go-title">${title}</p>
      <p class="text-label go-stat">DURATION: ${dur}</p>
      <p class="text-label go-stat">HULL REMAINING: ${hull}</p>
      ${hasDebrief ? '<a class="btn btn--secondary go-btn" href="/client/debrief/" target="_blank">VIEW DEBRIEF</a>' : ''}
      <a class="btn btn--primary go-btn" href="/client/lobby/">RETURN TO LOBBY</a>
    </div>`;
  el.style.display = 'flex';
}
