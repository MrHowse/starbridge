/**
 * audio_events.js — Event sounds for Starbridge.
 *
 * Registers one-shot event sound presets into the SoundBank:
 *   beam_fire, beam_fire_enemy, torpedo_launch, torpedo_impact,
 *   shield_hit_front, shield_hit_rear, hull_hit, system_damage,
 *   scan_complete, incoming_transmission, boarding_alert,
 *   door_seal, door_unseal, marine_combat, explosion,
 *   puzzle_success, puzzle_failure, puzzle_timeout_tick,
 *   victory, defeat
 *
 * Import this module once per station to register the presets.
 */

import { registerSound } from './audio.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Create a one-shot noise burst via AudioBuffer. Returns [source, gain]. */
function _noiseShot(ctx, gains, category, durationSec, filterFreq, filterQ = 1, filterType = 'bandpass') {
    const ambGain = gains[category];
    if (!ambGain) return null;

    const bufLen = Math.ceil(ctx.sampleRate * durationSec);
    const buf = ctx.createBuffer(1, bufLen, ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < bufLen; i++) data[i] = Math.random() * 2 - 1;

    const src = ctx.createBufferSource();
    src.buffer = buf;

    const filter = ctx.createBiquadFilter();
    filter.type = filterType;
    filter.frequency.value = filterFreq;
    filter.Q.value = filterQ;

    const g = ctx.createGain();
    src.connect(filter);
    filter.connect(g);
    g.connect(ambGain);
    return { src, filter, g };
}

/** Linear envelope: attack → sustain → decay. */
function _envelope(gainNode, ctx, peak, attackSec, sustainSec, decaySec) {
    const t = ctx.currentTime;
    gainNode.gain.setValueAtTime(0, t);
    gainNode.gain.linearRampToValueAtTime(peak, t + attackSec);
    gainNode.gain.setValueAtTime(peak, t + attackSec + sustainSec);
    gainNode.gain.linearRampToValueAtTime(0, t + attackSec + sustainSec + decaySec);
}

// ---------------------------------------------------------------------------
// Weapons
// ---------------------------------------------------------------------------

registerSound('beam_fire', (ctx, gains) => {
    // Sharp electrical discharge: high-frequency sweep down, 200ms
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(2400, ctx.currentTime);
    osc.frequency.linearRampToValueAtTime(600, ctx.currentTime + 0.2);
    _envelope(g, ctx, 0.25, 0.005, 0, 0.18);
    osc.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.25);
});

registerSound('beam_fire_enemy', (ctx, gains) => {
    // Lower, distorted — threatening
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const filter = ctx.createBiquadFilter();
    const g = ctx.createGain();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(900, ctx.currentTime);
    osc.frequency.linearRampToValueAtTime(250, ctx.currentTime + 0.25);
    filter.type = 'lowpass'; filter.frequency.value = 1200;
    _envelope(g, ctx, 0.2, 0.005, 0, 0.22);
    osc.connect(filter); filter.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.3);
});

registerSound('torpedo_launch', (ctx, gains) => {
    // Mechanical thunk → whoosh, 500ms
    const evGain = gains.events;
    if (!evGain) return;

    // Thunk: noise burst
    const shot = _noiseShot(ctx, gains, 'events', 0.5, 200, 2, 'bandpass');
    if (!shot) return;
    const t = ctx.currentTime;
    shot.g.gain.setValueAtTime(0, t);
    shot.g.gain.linearRampToValueAtTime(0.35, t + 0.02);
    shot.g.gain.linearRampToValueAtTime(0.05, t + 0.12);
    // Whoosh: high-pass filtered noise fading out
    shot.filter.frequency.linearRampToValueAtTime(2000, t + 0.5);
    shot.filter.type = 'highpass';
    shot.g.gain.linearRampToValueAtTime(0, t + 0.5);
    shot.src.start(t);
    shot.src.stop(t + 0.55);
});

registerSound('torpedo_impact', (ctx, gains) => {
    // Deep bass hit: sub-oscillator pulse
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine'; osc.frequency.value = 55;
    _envelope(g, ctx, 0.5, 0.01, 0.05, 0.4);
    osc.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.6);

    // Noise layer
    const shot = _noiseShot(ctx, gains, 'events', 0.5, 180, 1.5, 'bandpass');
    if (shot) {
        _envelope(shot.g, ctx, 0.3, 0.01, 0.05, 0.35);
        shot.src.start(); shot.src.stop(ctx.currentTime + 0.55);
    }
});

// ---------------------------------------------------------------------------
// Combat / damage
// ---------------------------------------------------------------------------

registerSound('shield_hit_front', (ctx, gains) => {
    // Crackling energy — high-pass noise burst
    const shot = _noiseShot(ctx, gains, 'events', 0.25, 3000, 2, 'highpass');
    if (!shot) return;
    _envelope(shot.g, ctx, 0.3, 0.005, 0.02, 0.2);
    shot.src.start(); shot.src.stop(ctx.currentTime + 0.3);
});

registerSound('shield_hit_rear', (ctx, gains) => {
    // Same, slightly lower pitched
    const shot = _noiseShot(ctx, gains, 'events', 0.25, 1800, 2, 'highpass');
    if (!shot) return;
    _envelope(shot.g, ctx, 0.25, 0.005, 0.02, 0.2);
    shot.src.start(); shot.src.stop(ctx.currentTime + 0.3);
});

registerSound('hull_hit', (ctx, gains, { intensity = 1.0 } = {}) => {
    // Metallic crunch — bandpass noise, bass heavy
    const evGain = gains.events;
    if (!evGain) return;
    const shot = _noiseShot(ctx, gains, 'events', 0.4, 350, 1.2, 'bandpass');
    if (!shot) return;
    _envelope(shot.g, ctx, 0.4 * intensity, 0.01, 0.05, 0.3);
    shot.src.start(); shot.src.stop(ctx.currentTime + 0.45);

    // Sub-bass thud
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine'; osc.frequency.value = 80;
    _envelope(g, ctx, 0.4 * intensity, 0.01, 0, 0.25);
    osc.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.35);
});

registerSound('system_damage', (ctx, gains) => {
    // Electrical sparking — random high-frequency clicks
    const evGain = gains.events;
    if (!evGain) return;
    const numClicks = 5 + Math.floor(Math.random() * 5);
    for (let i = 0; i < numClicks; i++) {
        const delay = Math.random() * 0.3;
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'square';
        osc.frequency.value = 1800 + Math.random() * 2000;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.15, ctx.currentTime + delay + 0.005);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.03);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.04);
    }
});

registerSound('explosion', (ctx, gains) => {
    // Expanding noise burst with reverb tail, 1 second
    const evGain = gains.events;
    if (!evGain) return;
    const shot = _noiseShot(ctx, gains, 'events', 1.0, 300, 0.8, 'lowpass');
    if (!shot) return;
    shot.g.gain.setValueAtTime(0, ctx.currentTime);
    shot.g.gain.linearRampToValueAtTime(0.5, ctx.currentTime + 0.05);
    shot.g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + 0.3);
    shot.g.gain.linearRampToValueAtTime(0, ctx.currentTime + 1.0);
    shot.src.start(); shot.src.stop(ctx.currentTime + 1.1);
});

// ---------------------------------------------------------------------------
// Science / Comms
// ---------------------------------------------------------------------------

registerSound('scan_complete', (ctx, gains) => {
    // Two-tone ascending chime — clean sine waves
    const evGain = gains.events;
    if (!evGain) return;
    [[523, 0], [659, 0.15], [784, 0.3]].forEach(([freq, delay]) => {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'sine'; osc.frequency.value = freq;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + delay + 0.02);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.25);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.3);
    });
});

registerSound('incoming_transmission', (ctx, gains) => {
    // Three short beeps, ascending pitch
    const evGain = gains.events;
    if (!evGain) return;
    [880, 1109, 1320].forEach((freq, i) => {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'sine'; osc.frequency.value = freq;
        const delay = i * 0.18;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + delay + 0.02);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.12);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.15);
    });
});

// ---------------------------------------------------------------------------
// Security / Boarding
// ---------------------------------------------------------------------------

registerSound('boarding_alert', (ctx, gains) => {
    // Urgent proximity alarm — fast pulse
    const evGain = gains.events;
    if (!evGain) return;
    for (let i = 0; i < 6; i++) {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'square'; osc.frequency.value = i % 2 === 0 ? 660 : 550;
        const delay = i * 0.15;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.25, ctx.currentTime + delay + 0.01);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.12);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.14);
    }
});

registerSound('door_seal', (ctx, gains) => {
    // Pneumatic hiss → mechanical clunk
    const evGain = gains.events;
    if (!evGain) return;
    // Hiss
    const shot = _noiseShot(ctx, gains, 'events', 0.3, 2000, 1, 'bandpass');
    if (shot) {
        shot.g.gain.setValueAtTime(0, ctx.currentTime);
        shot.g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + 0.05);
        shot.g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.3);
        shot.src.start(); shot.src.stop(ctx.currentTime + 0.35);
    }
    // Clunk
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine'; osc.frequency.value = 120;
    g.gain.setValueAtTime(0, ctx.currentTime + 0.28);
    g.gain.linearRampToValueAtTime(0.3, ctx.currentTime + 0.3);
    g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.4);
    osc.connect(g); g.connect(evGain);
    osc.start(ctx.currentTime + 0.28); osc.stop(ctx.currentTime + 0.45);
});

registerSound('door_unseal', (ctx, gains) => {
    // Reverse: click → hiss
    const evGain = gains.events;
    if (!evGain) return;
    // Click
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine'; osc.frequency.value = 150;
    g.gain.setValueAtTime(0, ctx.currentTime);
    g.gain.linearRampToValueAtTime(0.3, ctx.currentTime + 0.01);
    g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.06);
    osc.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.08);
    // Hiss
    const shot = _noiseShot(ctx, gains, 'events', 0.3, 1600, 1, 'bandpass');
    if (shot) {
        shot.g.gain.setValueAtTime(0, ctx.currentTime + 0.06);
        shot.g.gain.linearRampToValueAtTime(0.15, ctx.currentTime + 0.12);
        shot.g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.35);
        shot.src.start(ctx.currentTime + 0.06); shot.src.stop(ctx.currentTime + 0.4);
    }
});

registerSound('marine_combat', (ctx, gains) => {
    // Muffled distant gunfire — low-pass noise bursts
    const evGain = gains.events;
    if (!evGain) return;
    const numShots = 2 + Math.floor(Math.random() * 3);
    for (let i = 0; i < numShots; i++) {
        const delay = Math.random() * 0.4;
        const shot = _noiseShot(ctx, gains, 'events', 0.15, 400, 2, 'lowpass');
        if (!shot) continue;
        shot.g.gain.setValueAtTime(0, ctx.currentTime + delay);
        shot.g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + delay + 0.01);
        shot.g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.12);
        shot.src.start(ctx.currentTime + delay);
        shot.src.stop(ctx.currentTime + delay + 0.18);
    }
});

// ---------------------------------------------------------------------------
// Puzzle / Mission
// ---------------------------------------------------------------------------

registerSound('puzzle_success', (ctx, gains) => {
    // Ascending major arpeggio — three clean sine tones
    const evGain = gains.events;
    if (!evGain) return;
    [523, 659, 784, 1047].forEach((freq, i) => {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'sine'; osc.frequency.value = freq;
        const delay = i * 0.1;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.25, ctx.currentTime + delay + 0.03);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.35);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.4);
    });
});

registerSound('puzzle_failure', (ctx, gains) => {
    // Descending minor — two dull tones
    const evGain = gains.events;
    if (!evGain) return;
    [[440, 0], [349, 0.2]].forEach(([freq, delay]) => {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'sawtooth'; osc.frequency.value = freq;
        const filter = ctx.createBiquadFilter();
        filter.type = 'lowpass'; filter.frequency.value = 800;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + delay + 0.03);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.4);
        osc.connect(filter); filter.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.5);
    });
});

registerSound('puzzle_timeout_tick', (ctx, gains) => {
    // Single quiet click/tick for countdown warnings
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'square'; osc.frequency.value = 1200;
    g.gain.setValueAtTime(0, ctx.currentTime);
    g.gain.linearRampToValueAtTime(0.12, ctx.currentTime + 0.005);
    g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.04);
    osc.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.05);
});

// ---------------------------------------------------------------------------
// Game over
// ---------------------------------------------------------------------------

registerSound('victory', (ctx, gains) => {
    // Triumphant chord — stacked sawtooth with slow attack
    const evGain = gains.events;
    if (!evGain) return;
    [261, 329, 392, 523].forEach((freq, i) => {
        const osc = ctx.createOscillator();
        const filter = ctx.createBiquadFilter();
        const g = ctx.createGain();
        osc.type = 'sawtooth'; osc.frequency.value = freq;
        filter.type = 'lowpass'; filter.frequency.value = 2000;
        g.gain.setValueAtTime(0, ctx.currentTime);
        g.gain.linearRampToValueAtTime(0.15, ctx.currentTime + 0.8);
        g.gain.linearRampToValueAtTime(0.1, ctx.currentTime + 2.0);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + 3.5);
        osc.connect(filter); filter.connect(g); g.connect(evGain);
        osc.start(); osc.stop(ctx.currentTime + 3.8);
    });
});

registerSound('defeat', (ctx, gains) => {
    // Low ominous drone fading to silence
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine'; osc.frequency.value = 55;
    g.gain.setValueAtTime(0, ctx.currentTime);
    g.gain.linearRampToValueAtTime(0.35, ctx.currentTime + 0.5);
    g.gain.setValueAtTime(0.35, ctx.currentTime + 1.5);
    g.gain.linearRampToValueAtTime(0, ctx.currentTime + 4.0);
    osc.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 4.5);
});

// ---------------------------------------------------------------------------
// Flight Ops
// ---------------------------------------------------------------------------

registerSound('drone_launch', (ctx, gains) => {
    // Rising noise through highpass filter 400→3000 Hz, 400ms (catapult whoosh)
    const shot = _noiseShot(ctx, gains, 'events', 0.4, 400, 1.5, 'highpass');
    if (!shot) return;
    shot.filter.frequency.linearRampToValueAtTime(3000, ctx.currentTime + 0.4);
    _envelope(shot.g, ctx, 0.35, 0.02, 0.1, 0.28);
    shot.src.start(); shot.src.stop(ctx.currentTime + 0.45);
});

registerSound('drone_recovery', (ctx, gains) => {
    // Descending sine 800→300 Hz, 500ms — landing confirmed
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(800, ctx.currentTime);
    osc.frequency.linearRampToValueAtTime(300, ctx.currentTime + 0.5);
    _envelope(g, ctx, 0.25, 0.02, 0.15, 0.33);
    osc.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.55);
});

registerSound('drone_destroyed', (ctx, gains) => {
    // Explosion + static burst
    const evGain = gains.events;
    if (!evGain) return;
    // Low-freq explosion
    const shot = _noiseShot(ctx, gains, 'events', 0.5, 300, 0.8, 'lowpass');
    if (shot) {
        _envelope(shot.g, ctx, 0.4, 0.01, 0.05, 0.4);
        shot.src.start(); shot.src.stop(ctx.currentTime + 0.55);
    }
    // High-freq static crackle
    const crackle = _noiseShot(ctx, gains, 'events', 0.3, 4000, 2, 'highpass');
    if (crackle) {
        _envelope(crackle.g, ctx, 0.2, 0.05, 0.05, 0.2);
        crackle.src.start(); crackle.src.stop(ctx.currentTime + 0.35);
    }
});

registerSound('drone_lost', (ctx, gains) => {
    // Slow descending two-tone sine 440→330 Hz, 600ms — solemn
    const evGain = gains.events;
    if (!evGain) return;
    [[440, 0], [330, 0.3]].forEach(([freq, delay]) => {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'sine'; osc.frequency.value = freq;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + delay + 0.03);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.28);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.3);
    });
});

registerSound('bingo_fuel', (ctx, gains) => {
    // 4-pulse square 600 Hz alarm, 120ms spacing
    const evGain = gains.events;
    if (!evGain) return;
    for (let i = 0; i < 4; i++) {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'square'; osc.frequency.value = 600;
        const delay = i * 0.12;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + delay + 0.01);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.08);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.1);
    }
});

registerSound('warning', (ctx, gains) => {
    // 3-pulse alternating square 500/400 Hz
    const evGain = gains.events;
    if (!evGain) return;
    for (let i = 0; i < 3; i++) {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'square'; osc.frequency.value = i % 2 === 0 ? 500 : 400;
        const delay = i * 0.15;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + delay + 0.01);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.12);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.14);
    }
});

registerSound('bolter', (ctx, gains) => {
    // Harsh sawtooth 150 Hz through bandpass, 300ms — missed landing buzzer
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const filter = ctx.createBiquadFilter();
    const g = ctx.createGain();
    osc.type = 'sawtooth'; osc.frequency.value = 150;
    filter.type = 'bandpass'; filter.frequency.value = 400; filter.Q.value = 2;
    _envelope(g, ctx, 0.3, 0.01, 0.1, 0.19);
    osc.connect(filter); filter.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.35);
});

registerSound('contact_ping', (ctx, gains) => {
    // Sine 1500 Hz, 150ms with quick decay — sonar-like proximity ping
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine'; osc.frequency.value = 1500;
    _envelope(g, ctx, 0.2, 0.005, 0.02, 0.12);
    osc.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.2);
});

registerSound('torpedo_hit', (ctx, gains) => {
    // Confirmed kill — deep bass hit + noise (torpedo_impact pattern)
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine'; osc.frequency.value = 55;
    _envelope(g, ctx, 0.5, 0.01, 0.05, 0.4);
    osc.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.6);
    const shot = _noiseShot(ctx, gains, 'events', 0.5, 180, 1.5, 'bandpass');
    if (shot) {
        _envelope(shot.g, ctx, 0.3, 0.01, 0.05, 0.35);
        shot.src.start(); shot.src.stop(ctx.currentTime + 0.55);
    }
});

registerSound('survivor_pickup', (ctx, gains) => {
    // Ascending 3-tone chime 659/784/988 Hz — rescue complete
    const evGain = gains.events;
    if (!evGain) return;
    [659, 784, 988].forEach((freq, i) => {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'sine'; osc.frequency.value = freq;
        const delay = i * 0.12;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.25, ctx.currentTime + delay + 0.02);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.25);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.3);
    });
});

registerSound('decoy_deploy', (ctx, gains) => {
    // Bandpass noise burst 1200 Hz, 200ms — electronic ejection
    const shot = _noiseShot(ctx, gains, 'events', 0.2, 1200, 3, 'bandpass');
    if (!shot) return;
    _envelope(shot.g, ctx, 0.3, 0.01, 0.05, 0.14);
    shot.src.start(); shot.src.stop(ctx.currentTime + 0.25);
});

registerSound('buoy_deploy', (ctx, gains) => {
    // Descending sine 2000→800 Hz, 300ms — sonar deployment ping
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(2000, ctx.currentTime);
    osc.frequency.linearRampToValueAtTime(800, ctx.currentTime + 0.3);
    _envelope(g, ctx, 0.2, 0.01, 0.08, 0.21);
    osc.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.35);
});

// ---------------------------------------------------------------------------
// Security
// ---------------------------------------------------------------------------

registerSound('alert', (ctx, gains) => {
    // 3-pulse square 800/600 Hz alternating — security incident alarm
    const evGain = gains.events;
    if (!evGain) return;
    for (let i = 0; i < 3; i++) {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'square'; osc.frequency.value = i % 2 === 0 ? 800 : 600;
        const delay = i * 0.12;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.22, ctx.currentTime + delay + 0.01);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.09);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.11);
    }
});
