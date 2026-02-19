/**
 * audio_ambient.js — Ambient audio layers for Starbridge.
 *
 * Registers ambient presets into the SoundBank:
 *   engine_hum       — pitch shifts with throttle; deepens on low engine power
 *   reactor_drone    — rises with total power draw; warning oscillation above 90%
 *   sensor_sweep     — soft pulse synced to radar sweep rotation
 *   life_support     — subtle white noise; cuts out when a deck decompresses
 *   alert_level      — atmosphere shift per alert level (green/yellow/red)
 *
 * Import this module once per station to register the presets.
 * The SoundBank must already be initialised before calling setAmbient().
 */

import { registerAmbient, getCtx, _registerAmbient, _stopAmbient } from './audio.js';

// ---------------------------------------------------------------------------
// Engine hum — always on during gameplay; pitch rises with throttle
// ---------------------------------------------------------------------------

registerAmbient('engine_hum', (ctx, gains, { throttle = 0.3, enginePower = 1.0 } = {}) => {
    const ambGain = gains.ambient;
    if (!ambGain) return;

    // Base frequency: 55 Hz (idle) → 110 Hz (full throttle), lower when engine underpowered
    const baseFreq = 55 + throttle * 55 * Math.max(0.3, enginePower);

    const existing = _ambientEngineHum;

    if (existing) {
        // Smooth frequency update on existing oscillators
        const now = ctx.currentTime;
        existing.osc1.frequency.linearRampToValueAtTime(baseFreq, now + 0.5);
        existing.osc2.frequency.linearRampToValueAtTime(baseFreq * 1.5, now + 0.5);
        existing.osc3.frequency.linearRampToValueAtTime(baseFreq * 2.01, now + 0.5);
        return;
    }

    // Create engine hum: three detuned oscillators through bandpass filter
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    const osc3 = ctx.createOscillator();
    osc1.type = 'sawtooth';
    osc2.type = 'sawtooth';
    osc3.type = 'sawtooth';
    osc1.frequency.value = baseFreq;
    osc2.frequency.value = baseFreq * 1.5;
    osc3.frequency.value = baseFreq * 2.01;   // slight detune for warmth

    const filter = ctx.createBiquadFilter();
    filter.type = 'bandpass';
    filter.frequency.value = 120;
    filter.Q.value = 0.8;

    // LFO for subtle pitch wobble (0.1 Hz, ±2 Hz)
    const lfo = ctx.createOscillator();
    const lfoGain = ctx.createGain();
    lfo.frequency.value = 0.1;
    lfoGain.gain.value = 2;
    lfo.connect(lfoGain);
    lfoGain.connect(osc1.frequency);

    const envGain = ctx.createGain();
    envGain.gain.value = 0;

    osc1.connect(filter);
    osc2.connect(filter);
    osc3.connect(filter);
    filter.connect(envGain);
    envGain.connect(ambGain);

    osc1.start(); osc2.start(); osc3.start(); lfo.start();

    // Fade in over 2s
    envGain.gain.linearRampToValueAtTime(0.18, ctx.currentTime + 2.0);

    _ambientEngineHum = { osc1, osc2, osc3, lfo, filter, envGain };
    _registerAmbient('engine_hum', () => {
        const t = ctx.currentTime;
        envGain.gain.linearRampToValueAtTime(0, t + 1.0);
        setTimeout(() => {
            try { osc1.stop(); osc2.stop(); osc3.stop(); lfo.stop(); } catch (_) {}
        }, 1200);
        _ambientEngineHum = null;
    });
});

let _ambientEngineHum = null;

// ---------------------------------------------------------------------------
// Reactor drone — Engineering station; rises with power draw
// ---------------------------------------------------------------------------

registerAmbient('reactor_drone', (ctx, gains, { powerLoad = 1.0 } = {}) => {
    const ambGain = gains.ambient;
    if (!ambGain) return;

    // Power load 0–1 range (1 = budget full, >1 = overclock)
    const isWarning = powerLoad > 0.9;
    const baseFreq = 40 + powerLoad * 30;   // 40–70 Hz

    const existing = _ambientReactor;
    if (existing) {
        const now = ctx.currentTime;
        existing.osc.frequency.linearRampToValueAtTime(baseFreq, now + 0.3);
        existing.lfo.frequency.linearRampToValueAtTime(isWarning ? 3.0 : 0.05, now + 0.3);
        return;
    }

    const osc = ctx.createOscillator();
    osc.type = 'sine';
    osc.frequency.value = baseFreq;

    const lfo = ctx.createOscillator();
    const lfoGain = ctx.createGain();
    lfo.type = 'sine';
    lfo.frequency.value = isWarning ? 3.0 : 0.05;
    lfoGain.gain.value = isWarning ? 8 : 1;
    lfo.connect(lfoGain);
    lfoGain.connect(osc.frequency);

    const envGain = ctx.createGain();
    envGain.gain.value = 0;

    osc.connect(envGain);
    envGain.connect(ambGain);
    osc.start(); lfo.start();
    envGain.gain.linearRampToValueAtTime(0.12, ctx.currentTime + 1.5);

    _ambientReactor = { osc, lfo };
    _registerAmbient('reactor_drone', () => {
        const t = ctx.currentTime;
        envGain.gain.linearRampToValueAtTime(0, t + 0.8);
        setTimeout(() => { try { osc.stop(); lfo.stop(); } catch (_) {} }, 1000);
        _ambientReactor = null;
    });
});

let _ambientReactor = null;

// ---------------------------------------------------------------------------
// Sensor sweep — Science station; soft pulse every few seconds
// ---------------------------------------------------------------------------

registerAmbient('sensor_sweep', (ctx, gains, { interval = 3.5 } = {}) => {
    const ambGain = gains.ambient;
    if (!ambGain) return;
    if (_ambientSensorSweepTimer) return; // already running

    function _pulse() {
        if (!ambGain) return;
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = 880;
        g.gain.value = 0;
        osc.connect(g);
        g.connect(ambGain);
        osc.start();
        const t = ctx.currentTime;
        g.gain.linearRampToValueAtTime(0.06, t + 0.04);
        g.gain.linearRampToValueAtTime(0, t + 0.3);
        osc.stop(t + 0.35);
    }

    _pulse();
    _ambientSensorSweepTimer = setInterval(_pulse, interval * 1000);

    _registerAmbient('sensor_sweep', () => {
        clearInterval(_ambientSensorSweepTimer);
        _ambientSensorSweepTimer = null;
    });
});

let _ambientSensorSweepTimer = null;

// ---------------------------------------------------------------------------
// Life support hiss — all stations; white noise baseline
// ---------------------------------------------------------------------------

registerAmbient('life_support', (ctx, gains, { active = true } = {}) => {
    const ambGain = gains.ambient;
    if (!ambGain) return;

    if (!active) {
        // Abrupt cut (decompression event — dramatic silence)
        _stopAmbient('life_support');
        return;
    }

    if (_ambientLifeSupport) return; // already running

    // White noise via AudioBuffer
    const bufLen = ctx.sampleRate * 2;
    const buf = ctx.createBuffer(1, bufLen, ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < bufLen; i++) data[i] = Math.random() * 2 - 1;

    const source = ctx.createBufferSource();
    source.buffer = buf;
    source.loop = true;

    const filter = ctx.createBiquadFilter();
    filter.type = 'bandpass';
    filter.frequency.value = 1200;
    filter.Q.value = 0.5;

    const envGain = ctx.createGain();
    envGain.gain.value = 0;

    source.connect(filter);
    filter.connect(envGain);
    envGain.connect(ambGain);
    source.start();
    envGain.gain.linearRampToValueAtTime(0.04, ctx.currentTime + 3.0);

    _ambientLifeSupport = source;
    _registerAmbient('life_support', () => {
        try { source.stop(); } catch (_) {}
        _ambientLifeSupport = null;
    });
});

let _ambientLifeSupport = null;

// ---------------------------------------------------------------------------
// Alert level atmosphere
// ---------------------------------------------------------------------------

registerAmbient('alert_level', (ctx, gains, { level = 'green' } = {}) => {
    const ambGain = gains.ambient;
    if (!ambGain) return;

    // Stop any previous alert ambient
    _stopAmbient('alert_green');
    _stopAmbient('alert_yellow');
    _stopAmbient('alert_red');

    if (level === 'green') {
        _startAlertGreen(ctx, ambGain);
    } else if (level === 'yellow') {
        _startAlertYellow(ctx, ambGain);
    } else if (level === 'red') {
        _startAlertRed(ctx, ambGain);
    }
});

function _startAlertGreen(ctx, ambGain) {
    // Barely audible low-frequency pad — two sine waves a fifth apart
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    osc1.type = 'sine'; osc1.frequency.value = 55;
    osc2.type = 'sine'; osc2.frequency.value = 82;
    const g = ctx.createGain(); g.gain.value = 0;
    osc1.connect(g); osc2.connect(g); g.connect(ambGain);
    osc1.start(); osc2.start();
    g.gain.linearRampToValueAtTime(0.06, ctx.currentTime + 3.0);
    _registerAmbient('alert_green', () => {
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + 1.0);
        setTimeout(() => { try { osc1.stop(); osc2.stop(); } catch (_) {} }, 1200);
    });
}

function _startAlertYellow(ctx, ambGain) {
    // Tension drone — sawtooth with slow LFO
    const osc = ctx.createOscillator();
    osc.type = 'sawtooth'; osc.frequency.value = 90;
    const lfo = ctx.createOscillator();
    const lfoGain = ctx.createGain();
    lfo.type = 'sine'; lfo.frequency.value = 0.3; lfoGain.gain.value = 4;
    lfo.connect(lfoGain); lfoGain.connect(osc.frequency);
    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass'; filter.frequency.value = 400;
    const g = ctx.createGain(); g.gain.value = 0;
    osc.connect(filter); filter.connect(g); g.connect(ambGain);
    osc.start(); lfo.start();
    g.gain.linearRampToValueAtTime(0.1, ctx.currentTime + 1.5);
    _registerAmbient('alert_yellow', () => {
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.8);
        setTimeout(() => { try { osc.stop(); lfo.stop(); } catch (_) {} }, 1000);
    });
}

function _startAlertRed(ctx, ambGain) {
    // Klaxon pulse — 1-second on/off cycle, filtered square wave
    if (_alertRedTimer) { clearInterval(_alertRedTimer); _alertRedTimer = null; }

    let _klaxonOn = false;
    function _klaxonCycle() {
        _klaxonOn = !_klaxonOn;
        if (!_klaxonOn) return;
        const osc = ctx.createOscillator();
        const filter = ctx.createBiquadFilter();
        const g = ctx.createGain();
        osc.type = 'square'; osc.frequency.value = 440;
        filter.type = 'bandpass'; filter.frequency.value = 800; filter.Q.value = 2;
        g.gain.value = 0;
        osc.connect(filter); filter.connect(g); g.connect(ambGain);
        osc.start();
        const t = ctx.currentTime;
        g.gain.linearRampToValueAtTime(0.15, t + 0.05);
        g.gain.linearRampToValueAtTime(0, t + 0.45);
        osc.stop(t + 0.5);
    }

    _klaxonCycle();
    _alertRedTimer = setInterval(_klaxonCycle, 1000);

    _registerAmbient('alert_red', () => {
        clearInterval(_alertRedTimer);
        _alertRedTimer = null;
    });
}

let _alertRedTimer = null;
