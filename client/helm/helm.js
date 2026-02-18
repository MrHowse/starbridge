/**
 * Starbridge — Helm Station
 *
 * Controls:
 *   A / ←   — Turn left  (5° per step)
 *   D / →   — Turn right (5° per step)
 *   W / ↑   — Throttle up   (5% per step)
 *   S / ↓   — Throttle down (5% per step)
 *   Click compass  — Set target heading
 *   Throttle slider — Set throttle directly
 *
 * Interpolation:
 *   The server ticks at 10 Hz. We store the previous and current server
 *   state and lerp between them based on time since the last tick, giving
 *   smooth 60 fps motion without waiting for the next server update.
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import { setStatusDot, setAlertLevel } from '../shared/ui_components.js';
import {
  lerp,
  lerpAngle,
  createStarfield,
  drawBackground,
  drawStarfield,
  drawCompass,
  drawMinimap,
} from '../shared/renderer.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TICK_MS        = 100;    // server tick interval — must match game_loop.py
const HEADING_STEP   = 5;      // degrees per key press
const THROTTLE_STEP  = 5;      // % per key press
const STAR_COUNT     = 180;

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusDotEl   = document.querySelector('[data-status-dot]');
const statusLabelEl = document.querySelector('[data-status-label]');
const standbyEl     = document.querySelector('[data-standby]');
const helmMainEl    = document.querySelector('[data-helm-main]');
const missionLabelEl = document.getElementById('mission-label');

const viewscreenCanvas  = document.getElementById('viewscreen');
const compassCanvas     = document.getElementById('compass');
const minimapCanvas     = document.getElementById('minimap');

const targetHdgDisplay  = document.getElementById('target-heading-display');
const throttleSlider    = document.getElementById('throttle-slider');
const throttleDisplay   = document.getElementById('throttle-display');
const throttleGaugeFill = document.getElementById('throttle-gauge-fill');
const speedBadge        = document.getElementById('speed-badge');

const telemHeading  = document.getElementById('telem-heading');
const telemSpeed    = document.getElementById('telem-speed');
const telemThrottle = document.getElementById('telem-throttle');
const telemPosX     = document.getElementById('telem-pos-x');
const telemPosY     = document.getElementById('telem-pos-y');

// ---------------------------------------------------------------------------
// Game state
// ---------------------------------------------------------------------------

let gameActive = false;

/**
 * Server-provided ship state snapshots.
 * prevState: the state before the most recent tick.
 * currState: the most recent tick state.
 * lastTickTime: performance.now() when currState arrived.
 */
const DEFAULT_STATE = {
  heading:  0,
  velocity: 0,
  throttle: 0,
  position: { x: 50_000, y: 50_000 },
};

let prevState    = null;
let currState    = null;
let lastTickTime = 0;

/** Player's commanded values (local authority — sent to server immediately). */
let targetHeading = 0;
let throttle      = 0;

// Held-key tracking for smooth repeat (processed in the rAF loop).
const heldKeys = new Set();
let   lastControlSend = 0;

// Starfield data (generated once).
const stars = createStarfield(STAR_COUNT);

// Canvas contexts (obtained after game start when canvases are visible).
let vsCtx  = null; // viewscreen
let cmpCtx = null; // compass
let mmCtx  = null; // minimap

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();
  });

  on('lobby.welcome', handleWelcome);
  on('game.started',  handleGameStarted);
  on('ship.state',    handleShipState);

  setupKeyboard();

  connect();
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function handleWelcome(payload) {
  // Nothing helm-specific needed from welcome; status dot handles connection.
  console.log('[helm] Connected as', payload.connection_id);
}

function handleGameStarted(payload) {
  missionLabelEl.textContent = payload.mission_name.toUpperCase();
  standbyEl.style.display    = 'none';
  helmMainEl.style.display   = 'grid';
  gameActive = true;

  // Defer canvas setup to the next frame so the grid layout is fully
  // computed before we read clientWidth/clientHeight for sizing.
  requestAnimationFrame(() => {
    vsCtx  = viewscreenCanvas.getContext('2d');
    cmpCtx = compassCanvas.getContext('2d');
    mmCtx  = minimapCanvas.getContext('2d');

    resizeViewscreen();
    window.addEventListener('resize', resizeViewscreen);

    requestAnimationFrame(renderLoop);
  });

  console.log(`[helm] Game started — mission: ${payload.mission_id}`);
}

function handleShipState(payload) {
  if (!gameActive) return;
  prevState    = currState;
  currState    = payload;
  lastTickTime = performance.now();
}

// ---------------------------------------------------------------------------
// Interpolation
// ---------------------------------------------------------------------------

/**
 * Return a ship state interpolated between prevState and currState based
 * on how far we are into the current tick period. Returns currState directly
 * if there is only one data point.
 */
function getInterpolatedState() {
  if (!currState) return DEFAULT_STATE;
  if (!prevState) return currState;

  const t = Math.min((performance.now() - lastTickTime) / TICK_MS, 1.0);
  return {
    heading:  lerpAngle(prevState.heading,    currState.heading,    t),
    velocity: lerp(prevState.velocity,        currState.velocity,   t),
    throttle: currState.throttle,
    position: {
      x: lerp(prevState.position.x, currState.position.x, t),
      y: lerp(prevState.position.y, currState.position.y, t),
    },
  };
}

// ---------------------------------------------------------------------------
// Render loop
// ---------------------------------------------------------------------------

function renderLoop(now) {
  if (!gameActive) return;

  processHeldKeys(now);

  const state = getInterpolatedState();
  if (state) {
    drawViewscreen(state);
    drawCompassPanel(state);
    drawMinimapPanel(state);
    updateTelemetry(state);
  }

  requestAnimationFrame(renderLoop);
}

// ---------------------------------------------------------------------------
// Canvas draws
// ---------------------------------------------------------------------------

function drawViewscreen(state) {
  const w = viewscreenCanvas.width;
  const h = viewscreenCanvas.height;
  drawBackground(vsCtx, w, h);
  drawStarfield(vsCtx, w, h, state.heading, state.position.x, state.position.y, stars);
}

function drawCompassPanel(state) {
  const size = compassCanvas.width; // always square
  drawCompass(cmpCtx, size, state.heading, targetHeading);
}

function drawMinimapPanel(state) {
  const size = minimapCanvas.width;
  drawMinimap(mmCtx, size, state.position.x, state.position.y, state.heading);
}

function updateTelemetry(state) {
  const hdg = Math.round(state.heading);
  const spd = state.velocity.toFixed(1);
  const thr = Math.round(state.throttle);
  const px  = Math.round(state.position.x);
  const py  = Math.round(state.position.y);

  telemHeading.textContent  = `${hdg.toString().padStart(3, '0')}°`;
  telemSpeed.textContent    = `${spd} u/s`;
  telemThrottle.textContent = `${thr}%`;
  telemPosX.textContent     = px.toLocaleString();
  telemPosY.textContent     = py.toLocaleString();
  speedBadge.textContent    = `${spd} u/s`;
}

// ---------------------------------------------------------------------------
// Viewscreen canvas resize
// ---------------------------------------------------------------------------

function resizeViewscreen() {
  const wrap = viewscreenCanvas.parentElement;
  viewscreenCanvas.width  = wrap.clientWidth;
  viewscreenCanvas.height = wrap.clientHeight;
}

// ---------------------------------------------------------------------------
// Keyboard controls
// ---------------------------------------------------------------------------

function setupKeyboard() {
  document.addEventListener('keydown', (e) => {
    const key = e.key.toLowerCase();
    if (['arrowleft','arrowright','arrowup','arrowdown','a','d','w','s'].includes(key)) {
      e.preventDefault();
      if (!heldKeys.has(key)) {
        // Immediate first press — apply once right away.
        applyControl(key);
      }
      heldKeys.add(key);
    }
  });

  document.addEventListener('keyup', (e) => {
    heldKeys.delete(e.key.toLowerCase());
  });

  // Throttle slider input.
  throttleSlider.addEventListener('input', () => {
    if (!gameActive) return;
    throttle = parseInt(throttleSlider.value, 10);
    send('helm.set_throttle', { throttle });
    updateThrottleUI();
  });

  // Compass click — set target heading from click angle.
  compassCanvas.addEventListener('click', (e) => {
    if (!gameActive) return;
    const state = getInterpolatedState();
    if (!state) return;

    const rect = compassCanvas.getBoundingClientRect();
    const cx   = compassCanvas.width  / 2;
    const cy   = compassCanvas.height / 2;
    // Scale from CSS pixels to canvas pixels.
    const scaleX = compassCanvas.width  / rect.width;
    const scaleY = compassCanvas.height / rect.height;
    const dx = (e.clientX - rect.left) * scaleX - cx;
    const dy = (e.clientY - rect.top)  * scaleY - cy;

    // atan2(dy, dx) = angle from +x axis (canvas Y down = CW).
    // To get heading: clickAngle + currentHeading + 90°.
    // (Derivation: the ring is rotated so currentHeading is at top, which is
    // the -π/2 position in canvas space. See renderer.js drawCompass notes.)
    const clickDeg = Math.atan2(dy, dx) * 180 / Math.PI;
    targetHeading  = ((clickDeg + state.heading + 90) % 360 + 360) % 360;
    send('helm.set_heading', { heading: targetHeading });
    updateTargetHdgDisplay();
  });
}

/**
 * Held-key processing — called every rAF frame, but rate-limited to avoid
 * flooding the server.
 */
function processHeldKeys(now) {
  if (!gameActive) return;
  if (now - lastControlSend < TICK_MS) return;   // send at most 10/sec

  let headingChanged  = false;
  let throttleChanged = false;

  if (heldKeys.has('arrowleft') || heldKeys.has('a')) {
    targetHeading  = (targetHeading - HEADING_STEP + 360) % 360;
    headingChanged = true;
  } else if (heldKeys.has('arrowright') || heldKeys.has('d')) {
    targetHeading  = (targetHeading + HEADING_STEP) % 360;
    headingChanged = true;
  }

  if (heldKeys.has('arrowup') || heldKeys.has('w')) {
    throttle        = Math.min(100, throttle + THROTTLE_STEP);
    throttleChanged = true;
  } else if (heldKeys.has('arrowdown') || heldKeys.has('s')) {
    throttle        = Math.max(0, throttle - THROTTLE_STEP);
    throttleChanged = true;
  }

  if (headingChanged)  { send('helm.set_heading',  { heading: targetHeading }); updateTargetHdgDisplay(); }
  if (throttleChanged) { send('helm.set_throttle', { throttle }); updateThrottleUI(); }

  if (headingChanged || throttleChanged) lastControlSend = now;
}

/**
 * Immediate single application of a control key (on first press).
 */
function applyControl(key) {
  if (!gameActive) return;

  let headingChanged  = false;
  let throttleChanged = false;

  if (key === 'arrowleft'  || key === 'a') { targetHeading = (targetHeading - HEADING_STEP + 360) % 360; headingChanged  = true; }
  if (key === 'arrowright' || key === 'd') { targetHeading = (targetHeading + HEADING_STEP) % 360;       headingChanged  = true; }
  if (key === 'arrowup'    || key === 'w') { throttle = Math.min(100, throttle + THROTTLE_STEP);         throttleChanged = true; }
  if (key === 'arrowdown'  || key === 's') { throttle = Math.max(0, throttle - THROTTLE_STEP);           throttleChanged = true; }

  if (headingChanged)  { send('helm.set_heading',  { heading: targetHeading }); updateTargetHdgDisplay(); }
  if (throttleChanged) { send('helm.set_throttle', { throttle }); updateThrottleUI(); }
  lastControlSend = performance.now();
}

// ---------------------------------------------------------------------------
// UI update helpers
// ---------------------------------------------------------------------------

function updateTargetHdgDisplay() {
  targetHdgDisplay.textContent = `${Math.round(targetHeading).toString().padStart(3, '0')}°`;
}

function updateThrottleUI() {
  const pct = Math.round(throttle);
  throttleDisplay.textContent     = pct.toString().padStart(3, '0');
  throttleSlider.value            = pct;
  throttleGaugeFill.style.width   = `${pct}%`;
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
