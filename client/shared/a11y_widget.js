/**
 * Starbridge — Accessibility Widget (v0.04j)
 *
 * Self-injecting floating settings button that appears on every page.
 * Provides quick-toggle for colour-blind mode and reduced motion mode.
 *
 * Include with a <script type="module"> tag after the closing body tag,
 * or import in station JS files.
 *
 * The widget auto-applies settings to <body> on load.
 */

import { initSettings, getSetting, toggleSetting } from './settings.js';

// ---------------------------------------------------------------------------
// CSS (injected once)
// ---------------------------------------------------------------------------

const CSS = `
/* Floating fallback (non-station pages: editor, admin, site) */
.a11y-widget {
  position: fixed;
  bottom: 44px;  /* clear the 2rem role bar + margin */
  right: 12px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
}

/* Inline header variant (station pages) */
.a11y-header-wrapper {
  position: absolute;
  top: 50%;
  right: 8px;
  transform: translateY(-50%);
  z-index: 800;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
}

.a11y-header-wrapper .a11y-panel {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 9999;
}

.a11y-toggle-btn {
  width: 32px;
  height: 32px;
  border: 1px solid rgba(0,255,65,.4);
  background: rgba(0,15,0,.9);
  color: rgba(0,255,65,.7);
  font-family: monospace;
  font-size: 14px;
  cursor: pointer;
  border-radius: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.2s, color 0.2s;
}

.a11y-toggle-btn:hover,
.a11y-toggle-btn:focus-visible {
  border-color: var(--primary, #00ff41);
  color: var(--primary, #00ff41);
}

.a11y-toggle-btn[aria-pressed="true"] {
  border-color: var(--primary, #00ff41);
  background: rgba(0,255,65,.12);
  color: var(--primary, #00ff41);
}

.a11y-panel {
  background: rgba(0,10,0,.95);
  border: 1px solid rgba(0,255,65,.4);
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 180px;
  border-radius: 3px;
}

.a11y-panel-hidden {
  display: none;
}

.a11y-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.a11y-label {
  font-family: monospace;
  font-size: 0.65rem;
  color: rgba(0,255,65,.7);
  letter-spacing: 0.06em;
}

.a11y-switch {
  position: relative;
  width: 34px;
  height: 18px;
}

.a11y-switch input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}

.a11y-switch-track {
  position: absolute;
  inset: 0;
  background: rgba(0,255,65,.15);
  border: 1px solid rgba(0,255,65,.3);
  border-radius: 9px;
  cursor: pointer;
  transition: background 0.2s;
}

.a11y-switch input:checked + .a11y-switch-track {
  background: rgba(0,255,65,.4);
  border-color: var(--primary, #00ff41);
}

.a11y-switch-track::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 12px;
  height: 12px;
  background: rgba(0,255,65,.6);
  border-radius: 50%;
  transition: transform 0.2s;
}

.a11y-switch input:checked + .a11y-switch-track::after {
  transform: translateX(16px);
  background: var(--primary, #00ff41);
}

.a11y-panel-title {
  font-family: monospace;
  font-size: 0.6rem;
  letter-spacing: 0.1em;
  color: rgba(0,255,65,.5);
  border-bottom: 1px solid rgba(0,255,65,.2);
  padding-bottom: 6px;
  margin-bottom: 2px;
}
`;

// ---------------------------------------------------------------------------
// Build widget DOM
// ---------------------------------------------------------------------------

function buildWidget() {
  // Inject CSS once
  if (!document.getElementById('a11y-widget-styles')) {
    const style = document.createElement('style');
    style.id = 'a11y-widget-styles';
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  // Settings panel (hidden initially)
  const panel = document.createElement('div');
  panel.className = 'a11y-panel a11y-panel-hidden';
  panel.id = 'a11y-panel';
  panel.innerHTML = `
    <div class="a11y-panel-title">ACCESSIBILITY</div>
    <div class="a11y-row">
      <span class="a11y-label" id="a11y-cb-label">COLOUR-BLIND</span>
      <label class="a11y-switch" aria-labelledby="a11y-cb-label">
        <input type="checkbox" id="a11y-cb-toggle" aria-label="Toggle colour-blind mode"
               ${getSetting('cb_mode') ? 'checked' : ''} />
        <span class="a11y-switch-track"></span>
      </label>
    </div>
    <div class="a11y-row">
      <span class="a11y-label" id="a11y-motion-label">REDUCE MOTION</span>
      <label class="a11y-switch" aria-labelledby="a11y-motion-label">
        <input type="checkbox" id="a11y-motion-toggle" aria-label="Toggle reduced motion"
               ${getSetting('no_motion') ? 'checked' : ''} />
        <span class="a11y-switch-track"></span>
      </label>
    </div>
  `;

  // Settings button
  const settingsBtn = document.createElement('button');
  settingsBtn.className = 'a11y-toggle-btn';
  settingsBtn.setAttribute('aria-expanded', 'false');
  settingsBtn.setAttribute('aria-controls', 'a11y-panel');
  settingsBtn.setAttribute('aria-label', 'Accessibility settings');
  settingsBtn.title = 'Accessibility settings';
  settingsBtn.textContent = '⚙';

  // On station pages, embed the button in the station header so it never
  // floats over interactive content.  On non-station pages (editor, admin,
  // site), fall back to fixed-position bottom-right corner.
  const headerEl = document.querySelector('.station-header');
  if (headerEl) {
    const wrapper = document.createElement('div');
    wrapper.className = 'a11y-header-wrapper';
    wrapper.setAttribute('role', 'complementary');
    wrapper.setAttribute('aria-label', 'Accessibility settings');
    wrapper.appendChild(panel);
    wrapper.appendChild(settingsBtn);
    headerEl.appendChild(wrapper);
  } else {
    const widget = document.createElement('div');
    widget.className = 'a11y-widget';
    widget.setAttribute('role', 'complementary');
    widget.setAttribute('aria-label', 'Accessibility settings');
    widget.appendChild(panel);
    widget.appendChild(settingsBtn);
    document.body.appendChild(widget);
  }

  // Live region for announcements
  let liveRegion = document.getElementById('a11y-live');
  if (!liveRegion) {
    liveRegion = document.createElement('div');
    liveRegion.id = 'a11y-live';
    liveRegion.className = 'a11y-live';
    liveRegion.setAttribute('aria-live', 'polite');
    liveRegion.setAttribute('aria-atomic', 'true');
    document.body.appendChild(liveRegion);
  }

  // ---------------------------------------------------------------------------
  // Event handlers
  // ---------------------------------------------------------------------------

  settingsBtn.addEventListener('click', () => {
    const expanded = settingsBtn.getAttribute('aria-expanded') === 'true';
    settingsBtn.setAttribute('aria-expanded', String(!expanded));
    panel.classList.toggle('a11y-panel-hidden', expanded);
  });

  document.getElementById('a11y-cb-toggle').addEventListener('change', (e) => {
    toggleSetting('cb_mode');
    announce(e.target.checked ? 'Colour-blind mode enabled' : 'Colour-blind mode disabled');
  });

  document.getElementById('a11y-motion-toggle').addEventListener('change', (e) => {
    toggleSetting('no_motion');
    announce(e.target.checked ? 'Reduced motion enabled' : 'Reduced motion disabled');
  });

  // Close panel on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && settingsBtn.getAttribute('aria-expanded') === 'true') {
      settingsBtn.setAttribute('aria-expanded', 'false');
      panel.classList.add('a11y-panel-hidden');
      settingsBtn.focus();
    }
  });

  // Listen for external settings changes (from other modules)
  document.addEventListener('settings-changed', () => {
    const cbEl = document.getElementById('a11y-cb-toggle');
    const moEl = document.getElementById('a11y-motion-toggle');
    if (cbEl) cbEl.checked = getSetting('cb_mode');
    if (moEl) moEl.checked = getSetting('no_motion');
  });
}

function announce(text) {
  const region = document.getElementById('a11y-live');
  if (region) {
    region.textContent = '';
    setTimeout(() => { region.textContent = text; }, 50);
  }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

function init() {
  initSettings();
  buildWidget();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init, { once: true });
} else {
  init();
}

export { announce };
