/**
 * audio_ui.js — UI feedback sounds for Starbridge.
 *
 * Registers short one-shot UI sounds into the SoundBank:
 *   button_click    — subtle mechanical click on any .btn click
 *   slider_change   — soft notch tick on range input change
 *   role_claimed    — acceptance chime (role card claimed)
 *   role_released   — soft descending tone (role released)
 *   error_buzz      — short buzz for rejected actions
 *
 * Import this module once per station to register the presets.
 */

import { registerSound } from './audio.js';

// ---------------------------------------------------------------------------
// UI sounds
// ---------------------------------------------------------------------------

registerSound('button_click', (ctx, gains) => {
    const uiGain = gains.ui;
    if (!uiGain) return;
    const bufLen = Math.ceil(ctx.sampleRate * 0.05);
    const buf = ctx.createBuffer(1, bufLen, ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < bufLen; i++) {
        data[i] = (Math.random() * 2 - 1) * (1 - i / bufLen);
    }
    const src = ctx.createBufferSource();
    src.buffer = buf;
    const filter = ctx.createBiquadFilter();
    filter.type = 'bandpass'; filter.frequency.value = 2400; filter.Q.value = 3;
    const g = ctx.createGain();
    g.gain.value = 0.18;
    src.connect(filter); filter.connect(g); g.connect(uiGain);
    src.start(); src.stop(ctx.currentTime + 0.06);
});

registerSound('slider_change', (ctx, gains) => {
    const uiGain = gains.ui;
    if (!uiGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine'; osc.frequency.value = 1800;
    g.gain.setValueAtTime(0, ctx.currentTime);
    g.gain.linearRampToValueAtTime(0.06, ctx.currentTime + 0.005);
    g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.02);
    osc.connect(g); g.connect(uiGain);
    osc.start(); osc.stop(ctx.currentTime + 0.025);
});

registerSound('role_claimed', (ctx, gains) => {
    // Acceptance chime — single clean tone
    const uiGain = gains.ui;
    if (!uiGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine'; osc.frequency.value = 880;
    g.gain.setValueAtTime(0, ctx.currentTime);
    g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + 0.02);
    g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.3);
    osc.connect(g); g.connect(uiGain);
    osc.start(); osc.stop(ctx.currentTime + 0.35);
});

registerSound('role_released', (ctx, gains) => {
    // Soft descending tone
    const uiGain = gains.ui;
    if (!uiGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(660, ctx.currentTime);
    osc.frequency.linearRampToValueAtTime(440, ctx.currentTime + 0.2);
    g.gain.setValueAtTime(0, ctx.currentTime);
    g.gain.linearRampToValueAtTime(0.15, ctx.currentTime + 0.02);
    g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.22);
    osc.connect(g); g.connect(uiGain);
    osc.start(); osc.stop(ctx.currentTime + 0.25);
});

registerSound('error_buzz', (ctx, gains) => {
    // Short buzz — low square wave, 100ms
    const uiGain = gains.ui;
    if (!uiGain) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'square'; osc.frequency.value = 120;
    g.gain.setValueAtTime(0, ctx.currentTime);
    g.gain.linearRampToValueAtTime(0.2, ctx.currentTime + 0.01);
    g.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.1);
    osc.connect(g); g.connect(uiGain);
    osc.start(); osc.stop(ctx.currentTime + 0.12);
});

// ---------------------------------------------------------------------------
// Auto-wire button click to all .btn elements (after DOM ready)
// ---------------------------------------------------------------------------

/**
 * Wire button click sounds to all .btn elements on the page.
 * Call this after DOM content is loaded. Can be called multiple times safely.
 */
export function wireButtonSounds(SoundBank) {
    // Use event delegation on document so dynamically added buttons are covered
    if (document._sbButtonSoundsWired) return;
    document._sbButtonSoundsWired = true;

    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.btn');
        if (btn) SoundBank.play('button_click');
    }, { capture: false });
}
