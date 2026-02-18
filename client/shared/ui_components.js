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
