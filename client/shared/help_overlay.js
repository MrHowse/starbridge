/**
 * help_overlay.js — Station contextual help system.
 *
 * Each station registers a help manifest — an array of { selector, text, position }
 * items — then calls initHelpOverlay(). Pressing F1 or clicking the "?" button
 * toggles an annotated overlay highlighting interactive elements.
 *
 * Usage in a station file:
 *   import { registerHelp, initHelpOverlay } from '../shared/help_overlay.js';
 *   registerHelp([
 *     { selector: '#throttle-slider', text: 'Ship speed 0–100%.', position: 'right' },
 *     { selector: '#compass-canvas', text: 'Click to set heading.', position: 'below' },
 *   ]);
 *   // ... in init():
 *   initHelpOverlay();
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _manifest = null;
let _overlayEl = null;
let _initialised = false;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Register the help manifest for this station.
 * Call before initHelpOverlay().
 * @param {Array<{selector: string, text: string, position?: string}>} items
 *   position: 'right' | 'left' | 'above' | 'below' (default 'right')
 */
export function registerHelp(items) {
    _manifest = items;
}

/**
 * Wire up the F1 key and optional "?" button. Call once in init().
 * Idempotent — safe to call multiple times.
 */
export function initHelpOverlay() {
    if (_initialised) return;
    _initialised = true;

    document.addEventListener('keydown', (e) => {
        if (e.key === 'F1') {
            e.preventDefault();
            _toggle();
        }
        if (e.key === 'Escape' && _overlayEl) {
            _close();
        }
    });

    // Wire "?" button if present in the station header.
    const btn = document.querySelector('[data-help-btn]');
    if (btn) btn.addEventListener('click', _toggle);
}

// ---------------------------------------------------------------------------
// Internal
// ---------------------------------------------------------------------------

function _toggle() {
    if (_overlayEl) { _close(); } else { _open(); }
}

function _open() {
    if (!_manifest || _manifest.length === 0) return;

    const overlay = document.createElement('div');
    overlay.className = 'help-overlay';
    _applyStyle(overlay, {
        position: 'fixed',
        inset: '0',
        zIndex: '9000',
        background: 'rgba(0, 10, 0, 0.88)',
        pointerEvents: 'all',
    });

    // Title bar
    const title = document.createElement('div');
    title.textContent = 'STATION REFERENCE  ·  PRESS F1, ESC, OR CLICK TO DISMISS';
    _applyStyle(title, {
        position: 'absolute',
        top: '16px',
        left: '50%',
        transform: 'translateX(-50%)',
        color: 'var(--primary, #00ff88)',
        font: '700 11px monospace',
        letterSpacing: '2px',
        whiteSpace: 'nowrap',
        pointerEvents: 'none',
    });
    overlay.appendChild(title);

    // Annotations
    for (const item of _manifest) {
        const el = document.querySelector(item.selector);
        if (!el) continue;

        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;

        // Highlight box around the element.
        const box = document.createElement('div');
        _applyStyle(box, {
            position: 'fixed',
            left: `${rect.left - 3}px`,
            top: `${rect.top - 3}px`,
            width: `${rect.width + 6}px`,
            height: `${rect.height + 6}px`,
            border: '2px solid var(--primary, #00ff88)',
            boxShadow: '0 0 10px rgba(0,255,136,0.4)',
            pointerEvents: 'none',
            borderRadius: '2px',
        });
        overlay.appendChild(box);

        // Label panel.
        const label = document.createElement('div');
        label.textContent = item.text;
        _applyStyle(label, {
            position: 'fixed',
            background: 'rgba(0, 18, 0, 0.95)',
            border: '1px solid var(--primary, #00ff88)',
            color: 'var(--primary, #00ff88)',
            font: '400 11px monospace',
            padding: '5px 10px',
            maxWidth: '220px',
            lineHeight: '1.5',
            pointerEvents: 'none',
            borderRadius: '2px',
            whiteSpace: 'normal',
        });

        // Position the label relative to the element.
        _positionLabel(label, rect, item.position || 'right');
        overlay.appendChild(label);
    }

    // Dismiss on click anywhere.
    overlay.addEventListener('click', _close);

    document.body.appendChild(overlay);
    _overlayEl = overlay;
}

function _close() {
    if (_overlayEl) {
        _overlayEl.remove();
        _overlayEl = null;
    }
}

function _positionLabel(label, rect, position) {
    const GAP = 10;
    switch (position) {
        case 'left':
            label.style.right = `${window.innerWidth - rect.left + GAP}px`;
            label.style.top   = `${rect.top + rect.height / 2 - 16}px`;
            break;
        case 'above':
            label.style.left  = `${Math.max(4, rect.left + rect.width / 2 - 110)}px`;
            label.style.bottom = `${window.innerHeight - rect.top + GAP}px`;
            break;
        case 'below':
            label.style.left  = `${Math.max(4, rect.left + rect.width / 2 - 110)}px`;
            label.style.top   = `${rect.bottom + GAP}px`;
            break;
        default: // 'right'
            label.style.left = `${rect.right + GAP}px`;
            label.style.top  = `${rect.top + rect.height / 2 - 16}px`;
            break;
    }
}

function _applyStyle(el, styles) {
    Object.assign(el.style, styles);
}
