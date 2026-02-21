/**
 * Starbridge — Settings module (v0.04j)
 *
 * Manages per-device persistent settings for colour-blind mode and
 * reduced-motion mode. Settings are stored in localStorage and applied
 * immediately by toggling CSS classes on <body>.
 *
 * Usage:
 *   import { initSettings, getSetting, toggleSetting } from '../shared/settings.js';
 *   initSettings();   // call once at page load
 *
 * Settings keys:
 *   'cb_mode'       — colour-blind-friendly palette (boolean)
 *   'no_motion'     — reduced motion (boolean)
 */

const STORAGE_KEY = 'starbridge_settings';

const _DEFAULTS = {
  cb_mode:   false,
  no_motion: false,
};

let _settings = { ..._DEFAULTS };

// ---------------------------------------------------------------------------
// Load / save
// ---------------------------------------------------------------------------

function _load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) Object.assign(_settings, JSON.parse(raw));
  } catch (_) { /* ignore */ }
}

function _save() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(_settings));
  } catch (_) { /* ignore */ }
}

// ---------------------------------------------------------------------------
// Apply settings to <body>
// ---------------------------------------------------------------------------

function _apply() {
  document.body.classList.toggle('cb-mode',   Boolean(_settings.cb_mode));
  document.body.classList.toggle('no-motion', Boolean(_settings.no_motion));
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Initialise settings from localStorage and apply CSS classes.
 * Call once at DOMContentLoaded (or import-time if DOM is ready).
 */
export function initSettings() {
  _load();
  _apply();
}

/**
 * Return the current value of a setting.
 * @param {string} key  — settings key
 * @returns {boolean}
 */
export function getSetting(key) {
  return Boolean(_settings[key]);
}

/**
 * Toggle a boolean setting, persist it, and re-apply CSS classes.
 * Dispatches a 'settings-changed' CustomEvent on document.
 * @param {string} key — settings key
 * @returns {boolean} new value
 */
export function toggleSetting(key) {
  _settings[key] = !_settings[key];
  _save();
  _apply();
  document.dispatchEvent(new CustomEvent('settings-changed', {
    detail: { key, value: _settings[key] },
  }));
  return Boolean(_settings[key]);
}

/**
 * Directly set a setting value.
 * @param {string}  key
 * @param {boolean} value
 */
export function setSetting(key, value) {
  _settings[key] = Boolean(value);
  _save();
  _apply();
  document.dispatchEvent(new CustomEvent('settings-changed', {
    detail: { key, value: _settings[key] },
  }));
}

// Auto-initialise if the DOM is already ready.
if (document.readyState !== 'loading') {
  initSettings();
} else {
  document.addEventListener('DOMContentLoaded', initSettings, { once: true });
}
