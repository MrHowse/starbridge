/**
 * audio_ops.js — Operations station event sounds for Starbridge.
 *
 * Registers one-shot event sound presets into the SoundBank:
 *   ops_assessment_complete, ops_sync_activated, ops_sync_broken,
 *   ops_threat_critical, ops_incoming_torpedo, ops_mission_complete,
 *   ops_advisory_sent, ops_feed_critical
 *
 * Import this module once per station to register the presets.
 */

import { registerSound } from './audio.js';

// ---------------------------------------------------------------------------
// Operations — Assessment & Analysis
// ---------------------------------------------------------------------------

registerSound('ops_assessment_complete', (ctx, gains) => {
    // Ascending two-tone chime — clean sine pair
    const evGain = gains.events;
    if (!evGain) return;
    [[587, 0], [784, 0.12]].forEach(([freq, delay]) => {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'sine'; osc.frequency.value = freq;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + delay + 0.02);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.3);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.35);
    });
});

// ---------------------------------------------------------------------------
// Operations — Coordination
// ---------------------------------------------------------------------------

registerSound('ops_sync_activated', (ctx, gains) => {
    // Positive connection tone — rising fifth interval
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(440, ctx.currentTime);
    osc.frequency.linearRampToValueAtTime(660, ctx.currentTime + 0.15);
    g.gain.setValueAtTime(0, ctx.currentTime);
    g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + 0.02);
    g.gain.setValueAtTime(0.2, ctx.currentTime + 0.15);
    g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.4);
    osc.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.45);
});

registerSound('ops_sync_broken', (ctx, gains) => {
    // Descending disconnect — falling minor third
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(660, ctx.currentTime);
    osc.frequency.linearRampToValueAtTime(440, ctx.currentTime + 0.2);
    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass'; filter.frequency.value = 1200;
    g.gain.setValueAtTime(0, ctx.currentTime);
    g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + 0.02);
    g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.35);
    osc.connect(filter); filter.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.4);
});

// ---------------------------------------------------------------------------
// Operations — Threat & Alert
// ---------------------------------------------------------------------------

registerSound('ops_threat_critical', (ctx, gains) => {
    // Urgent alarm — fast alternating two-tone pulse
    const evGain = gains.events;
    if (!evGain) return;
    for (let i = 0; i < 4; i++) {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'square';
        osc.frequency.value = i % 2 === 0 ? 880 : 700;
        const delay = i * 0.12;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + delay + 0.01);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.1);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.12);
    }
});

registerSound('ops_incoming_torpedo', (ctx, gains) => {
    // Fast alternating alert — rapid high-low warble
    const evGain = gains.events;
    if (!evGain) return;
    for (let i = 0; i < 6; i++) {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'square';
        osc.frequency.value = i % 2 === 0 ? 1100 : 800;
        const delay = i * 0.08;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.18, ctx.currentTime + delay + 0.005);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.07);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.08);
    }
});

// ---------------------------------------------------------------------------
// Operations — Mission & Communication
// ---------------------------------------------------------------------------

registerSound('ops_mission_complete', (ctx, gains) => {
    // Achievement chime — ascending major triad
    const evGain = gains.events;
    if (!evGain) return;
    [[523, 0], [659, 0.1], [784, 0.2]].forEach(([freq, delay]) => {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = 'sine'; osc.frequency.value = freq;
        g.gain.setValueAtTime(0, ctx.currentTime + delay);
        g.gain.linearRampToValueAtTime(0.22, ctx.currentTime + delay + 0.02);
        g.gain.linearRampToValueAtTime(0, ctx.currentTime + delay + 0.4);
        osc.connect(g); g.connect(evGain);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + 0.45);
    });
});

registerSound('ops_advisory_sent', (ctx, gains) => {
    // Soft confirmation — single gentle tone
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine'; osc.frequency.value = 698;
    g.gain.setValueAtTime(0, ctx.currentTime);
    g.gain.linearRampToValueAtTime(0.12, ctx.currentTime + 0.02);
    g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.2);
    osc.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.25);
});

registerSound('ops_feed_critical', (ctx, gains) => {
    // Subtle alert ping — short high sine blip
    const evGain = gains.events;
    if (!evGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine'; osc.frequency.value = 1047;
    g.gain.setValueAtTime(0, ctx.currentTime);
    g.gain.linearRampToValueAtTime(0.15, ctx.currentTime + 0.01);
    g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.12);
    osc.connect(g); g.connect(evGain);
    osc.start(); osc.stop(ctx.currentTime + 0.15);
});
