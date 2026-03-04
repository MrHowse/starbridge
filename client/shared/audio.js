/**
 * audio.js — SoundBank singleton for Starbridge.
 *
 * Procedural audio via Web Audio API. No audio files, no licensing.
 * Every sound is generated from oscillators, noise, filters, and envelopes.
 *
 * Usage:
 *   import { SoundBank } from '../shared/audio.js';
 *   SoundBank.init();
 *   SoundBank.play('beam_fire');
 *   SoundBank.setAmbient('engine_hum', { throttle: 0.6 });
 *   SoundBank.setVolume('ambient', 0.5);
 *   SoundBank.mute();
 *
 * Browser autoplay policy: AudioContext is created and resumed on first
 * user interaction. No sound plays before that moment.
 */

// ---------------------------------------------------------------------------
// AudioContext bootstrap (lazy, gated on user interaction)
// ---------------------------------------------------------------------------

let _ctx = null;
let _unlocked = false;

/**
 * Return the shared AudioContext, creating it on first call.
 * @returns {AudioContext}
 */
export function getCtx() {
    if (!_ctx) {
        _ctx = new (window.AudioContext || window.webkitAudioContext)();
    }
    return _ctx;
}

/**
 * Resume AudioContext on first user gesture. Installed once at init.
 */
function _installUnlockListener() {
    if (_unlocked) return;
    const unlock = async () => {
        if (_ctx && _ctx.state === 'suspended') {
            await _ctx.resume();
        }
        _unlocked = true;
        document.removeEventListener('click', unlock, true);
        document.removeEventListener('keydown', unlock, true);
        document.removeEventListener('touchstart', unlock, true);
    };
    document.addEventListener('click', unlock, true);
    document.addEventListener('keydown', unlock, true);
    document.addEventListener('touchstart', unlock, true);
}

// ---------------------------------------------------------------------------
// Gain bus architecture:
//   sound node → category gain → master gain → destination
// Three categories: ambient, events, ui
// ---------------------------------------------------------------------------

let _masterGain = null;
const _categoryGains = {};
let _muted = false;

const CATEGORIES = ['ambient', 'events', 'ui'];
const STORAGE_KEY = 'starbridge_audio_v1';

function _loadVolumes() {
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored) return JSON.parse(stored);
    } catch (_) { /* ignore parse errors */ }
    return { ambient: 0.4, events: 0.7, ui: 0.3, muted: false };
}

function _saveVolumes() {
    const data = { muted: _muted };
    for (const cat of CATEGORIES) {
        data[cat] = _categoryGains[cat] ? _categoryGains[cat]._volume : _defaultVolume(cat);
    }
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(data)); } catch (_) { /* ignore */ }
}

function _defaultVolume(cat) {
    return { ambient: 0.4, events: 0.7, ui: 0.3 }[cat] ?? 0.5;
}

// ---------------------------------------------------------------------------
// Ambient node registry — running ambient nodes keyed by name
// ---------------------------------------------------------------------------

const _ambientNodes = {};

export function _registerAmbient(name, stopFn) {
    _ambientNodes[name] = stopFn;
}

export function _stopAmbient(name) {
    if (_ambientNodes[name]) {
        try { _ambientNodes[name](); } catch (_) { /* ignore */ }
        delete _ambientNodes[name];
    }
}

// ---------------------------------------------------------------------------
// Sound and ambient registries — populated by importing the sub-modules
// ---------------------------------------------------------------------------

export const _SOUNDS = {};
export const _AMBIENT = {};

/** Register a named one-shot sound preset. */
export function registerSound(name, fn) { _SOUNDS[name] = fn; }

/** Register a named ambient layer preset. */
export function registerAmbient(name, fn) { _AMBIENT[name] = fn; }

// ---------------------------------------------------------------------------
// SoundBank public API
// ---------------------------------------------------------------------------

export const SoundBank = {
    /**
     * Initialise the audio system. Call once per station in init().
     * Idempotent — safe to call multiple times.
     */
    init() {
        if (_masterGain) return;

        const ctx = getCtx();
        _installUnlockListener();

        _masterGain = ctx.createGain();
        _masterGain.connect(ctx.destination);

        const saved = _loadVolumes();
        _muted = saved.muted || false;
        _masterGain.gain.value = _muted ? 0 : 1;

        for (const cat of CATEGORIES) {
            const g = ctx.createGain();
            g._volume = saved[cat] ?? _defaultVolume(cat);
            g.gain.value = _muted ? 0 : g._volume;
            g.connect(_masterGain);
            _categoryGains[cat] = g;
        }

        _mountVolumeUI();
    },

    /**
     * Play a named one-shot sound.
     * @param {string} name
     * @param {Object} [opts]
     */
    play(name, opts = {}) {
        if (!_masterGain) return;
        const ctx = getCtx();
        if (ctx.state !== 'running') return;
        const def = _SOUNDS[name];
        if (!def) { console.warn(`[audio] unknown sound: ${name}`); return; }
        try { def(ctx, _categoryGains, opts); } catch (e) {
            console.warn(`[audio] ${name} error:`, e);
        }
    },

    /**
     * Set or update a named ambient layer.
     * @param {string} name
     * @param {Object} [params]
     */
    setAmbient(name, params = {}) {
        if (!_masterGain) return;
        const ctx = getCtx();
        if (ctx.state !== 'running') return;
        const def = _AMBIENT[name];
        if (!def) { console.warn(`[audio] unknown ambient: ${name}`); return; }
        try { def(ctx, _categoryGains, params); } catch (e) {
            console.warn(`[audio] ambient ${name} error:`, e);
        }
    },

    /**
     * Stop a named ambient layer.
     * @param {string} name
     */
    stopAmbient(name) {
        _stopAmbient(name);
    },

    /**
     * Set volume for a category (0–1). Persisted to localStorage.
     * @param {'ambient'|'events'|'ui'} category
     * @param {number} volume
     */
    setVolume(category, volume) {
        const g = _categoryGains[category];
        if (!g) return;
        g._volume = Math.max(0, Math.min(1, volume));
        if (!_muted) g.gain.value = g._volume;
        _saveVolumes();
        _updateVolumeUI();
    },

    /**
     * Toggle master mute. Returns new muted state.
     * @returns {boolean}
     */
    mute() {
        _muted = !_muted;
        if (_masterGain) _masterGain.gain.value = _muted ? 0 : 1;
        _saveVolumes();
        _updateVolumeUI();
        return _muted;
    },

    /** @returns {boolean} */
    isMuted() { return _muted; },

    /** @returns {number} volume 0-1 for the given category */
    getVolume(category) {
        const g = _categoryGains[category];
        return g ? g._volume : 0;
    },

    /**
     * Expose category gain node for sub-modules that need direct access.
     * @param {'ambient'|'events'|'ui'} category
     * @returns {GainNode|undefined}
     */
    getCategoryGain(category) {
        return _categoryGains[category];
    },
};

// ---------------------------------------------------------------------------
// Volume control UI — small panel fixed to top-right
// ---------------------------------------------------------------------------

const VOL_UI_ID = 'sb-volume-panel';

function _mountVolumeUI() {
    if (document.getElementById(VOL_UI_ID)) {
        _updateVolumeUI();
        return;
    }

    // Inject CSS (once)
    if (!document.getElementById('sb-vol-css')) {
        const style = document.createElement('style');
        style.id = 'sb-vol-css';
        style.textContent = `
            #sb-volume-panel {
                position: fixed;
                top: 8px;
                right: 8px;
                z-index: 2000;
                display: flex;
                flex-direction: column;
                align-items: flex-end;
                gap: 4px;
                font-family: 'Share Tech Mono', 'Courier New', monospace;
            }
            .sb-vol-toggle {
                background: transparent;
                border: 1px solid var(--border-primary, rgba(0,255,65,0.3));
                color: var(--text-dim, rgba(0,255,65,0.4));
                padding: 3px 8px;
                font-size: 0.85rem;
                cursor: pointer;
                opacity: 0.7;
                transition: opacity 0.2s;
            }
            .sb-vol-toggle:hover { opacity: 1; color: var(--text-bright, #00ff41); }
            .sb-vol-drawer {
                background: var(--bg-panel, #0d0d0d);
                border: 1px solid var(--border-primary, rgba(0,255,65,0.3));
                box-shadow: 0 0 8px var(--primary-glow, rgba(0,255,65,0.15));
                padding: 8px 12px;
                min-width: 190px;
            }
            .sb-vol-row {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 6px;
            }
            .sb-vol-label {
                width: 58px;
                flex-shrink: 0;
                font-size: 0.875rem;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                color: var(--text-dim, rgba(0,255,65,0.4));
            }
            .sb-vol-slider {
                flex: 1;
                accent-color: var(--primary, #00ff41);
                cursor: pointer;
                height: 4px;
            }
            .sb-mute-btn {
                width: 100%;
                margin-top: 4px;
                background: transparent;
                border: 1px solid var(--border-primary, rgba(0,255,65,0.3));
                color: var(--text-normal, rgba(0,255,65,0.7));
                font-family: inherit;
                font-size: 0.875rem;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                padding: 3px 0;
                cursor: pointer;
                transition: all 0.2s;
            }
            .sb-mute-btn:hover {
                border-color: var(--primary, #00ff41);
                color: var(--text-bright, #00ff41);
            }
            .sb-mute-btn[data-muted="true"] {
                border-color: var(--hostile, #ff3333);
                color: var(--hostile, #ff3333);
            }
        `;
        document.head.appendChild(style);
    }

    const panel = document.createElement('div');
    panel.id = VOL_UI_ID;

    panel.innerHTML = `
        <button class="sb-vol-toggle" aria-label="Audio settings" title="Audio settings">&#128266;</button>
        <div class="sb-vol-drawer" hidden>
            <div class="sb-vol-row">
                <span class="sb-vol-label">Ambient</span>
                <input type="range" class="sb-vol-slider" data-cat="ambient" min="0" max="1" step="0.05">
            </div>
            <div class="sb-vol-row">
                <span class="sb-vol-label">Events</span>
                <input type="range" class="sb-vol-slider" data-cat="events" min="0" max="1" step="0.05">
            </div>
            <div class="sb-vol-row">
                <span class="sb-vol-label">UI</span>
                <input type="range" class="sb-vol-slider" data-cat="ui" min="0" max="1" step="0.05">
            </div>
            <button class="sb-mute-btn" data-muted="false">Mute</button>
        </div>
    `;

    document.body.appendChild(panel);

    const toggle = panel.querySelector('.sb-vol-toggle');
    const drawer = panel.querySelector('.sb-vol-drawer');
    const muteBtn = panel.querySelector('.sb-mute-btn');

    toggle.addEventListener('click', (e) => {
        e.stopPropagation();
        drawer.hidden = !drawer.hidden;
    });

    document.addEventListener('click', (e) => {
        if (!panel.contains(e.target)) drawer.hidden = true;
    });

    panel.querySelectorAll('.sb-vol-slider').forEach(slider => {
        slider.addEventListener('input', () => {
            SoundBank.setVolume(slider.dataset.cat, parseFloat(slider.value));
            SoundBank.play('slider_change');
        });
    });

    muteBtn.addEventListener('click', () => {
        const nowMuted = SoundBank.mute();
        muteBtn.dataset.muted = String(nowMuted);
        muteBtn.textContent = nowMuted ? 'Unmute' : 'Mute';
    });

    _updateVolumeUI();
}

function _updateVolumeUI() {
    const panel = document.getElementById(VOL_UI_ID);
    if (!panel) return;

    for (const cat of CATEGORIES) {
        const slider = panel.querySelector(`[data-cat="${cat}"]`);
        if (slider) slider.value = SoundBank.getVolume(cat);
    }
    const muteBtn = panel.querySelector('.sb-mute-btn');
    if (muteBtn) {
        muteBtn.dataset.muted = String(_muted);
        muteBtn.textContent = _muted ? 'Unmute' : 'Mute';
    }
    const toggle = panel.querySelector('.sb-vol-toggle');
    if (toggle) toggle.textContent = _muted ? '🔇' : '🔊';
}
