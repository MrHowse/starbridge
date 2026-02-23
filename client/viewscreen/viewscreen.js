/**
 * Viewscreen Station — Phase 7 full implementation.
 *
 * Display-only forward view for a shared screen / TV.
 * No controls, no role assignment in the crew roster — just the showpiece.
 *
 * Rendering is heading-up (ship's forward direction = screen up).
 * Canvas fills the full viewport.
 *
 * Visual effects:
 *   - Parallax starfield (from renderer.js, heading-adjusted)
 *   - Enemy wireframe shapes (diamond/triangle/hexagon)
 *   - Torpedo trails (5-dot fade ring buffer)
 *   - Beam flash (bright line, 200 ms fade)
 *   - Explosion rings (3 wireframe circles expanding, 400 ms)
 *   - Shield arc flash on hull hit (300 ms)
 *   - Screen-edge red flash on hull hit
 *   - HUD strip: mission name, hull/shield gauges, heading
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import { setStatusDot, setAlertLevel, showBriefing } from '../shared/ui_components.js';
import { initRoleBar } from '../shared/role_bar.js';
import { initCrewRoster } from '../shared/crew_roster.js';
import {
  C_PRIMARY, C_PRIMARY_DIM,
  createStarfield, drawBackground, drawStarfield,
} from '../shared/renderer.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Half-width of the forward view in world units. Smaller = more zoomed in. */
const VIEW_RADIUS  = 18_000;

/** How many trail points to keep per torpedo. */
const TRAIL_LENGTH = 6;

/** Enemy wireframe shapes — matches weapons.js and captain.js. */
const ENEMY_SHAPES = {
  scout:     { size: 8,  color: '#ff4040' },
  cruiser:   { size: 12, color: '#ff4040' },
  destroyer: { size: 16, color: '#ff4040' },
};

const BEAM_DURATION      = 200;  // ms
const EXPLOSION_DURATION = 400;  // ms
const SHIELD_ARC_DURATION = 300; // ms
const HIT_FLASH_MS       = 250;  // ms

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const canvas        = document.getElementById('viewscreen-canvas');
const ctx           = canvas ? canvas.getContext('2d') : null;
const hudEl         = document.querySelector('[data-hud]');
const standbyEl     = document.querySelector('[data-standby]');
const statusDotEl   = document.querySelector('[data-status-dot]');
const statusDotSbEl = document.querySelector('[data-status-dot-sb]');
const statusLabelEl = document.querySelector('[data-status-label]');
const statusLabelSbEl = document.querySelector('[data-status-label-sb]');
const missionNameEl = document.querySelector('[data-mission-name]');
const hullFillEl    = document.querySelector('[data-hull-fill]');
const hullTextEl    = document.querySelector('[data-hull-text]');
const shieldFwdFillEl = document.querySelector('[data-shield-fwd-fill]');
const shieldFwdTextEl = document.querySelector('[data-shield-fwd-text]');
const shieldAftFillEl = document.querySelector('[data-shield-aft-fill]');
const shieldAftTextEl = document.querySelector('[data-shield-aft-text]');
const hdgTextEl     = document.querySelector('[data-hdg-text]');
const gameOverEl    = document.querySelector('[data-game-over]');
const gameOverTitleEl = document.querySelector('[data-game-over-title]');
const gameOverBodyEl  = document.querySelector('[data-game-over-body]');
const flashEl       = document.querySelector('[data-flash]');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let gameActive = false;
let shipState  = null;
let entities   = { enemies: [], torpedoes: [] };

/** Map<torpedoId, [{x, y}]> — ring buffer of recent positions. */
const torpedoTrails = new Map();

/** Active beam flashes: [{fromX, fromY, toX, toY, startTime}] */
const beamFlashes = [];

/** Active explosions: [{x, y, startTime}] */
const explosions = [];

/** Active shield arcs: [{angle, startTime}] — angle in radians, attacker side */
const shieldArcs = [];

/** Starfield data */
const stars = createStarfield(300);

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    if (statusDotSbEl) setStatusDot(statusDotSbEl, status);
    const label = status.toUpperCase();
    if (statusLabelEl)   statusLabelEl.textContent   = label;
    if (statusLabelSbEl) statusLabelSbEl.textContent = label;
  });

  on('lobby.welcome',      handleWelcome);
  on('game.started',       handleGameStarted);
  on('ship.state',         handleShipState);
  on('ship.alert_changed', ({ level }) => setAlertLevel(level));
  on('world.entities',     handleWorldEntities);
  on('weapons.beam_fired', handleBeamFired);
  on('weapons.torpedo_hit', handleTorpedoHit);
  on('ship.hull_hit',      handleHullHit);
  on('game.over',          handleGameOver);

  window.addEventListener('resize', resizeCanvas);
  initRoleBar(send, 'viewscreen');
  initCrewRoster(send);

  connect();
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function handleWelcome() {
  // Viewscreen is an observer — claim the role so broadcast_to_roles works,
  // but it doesn't occupy a crew slot in the lobby grid.
  send('lobby.claim_role', { role: 'viewscreen', player_name: 'VIEWSCREEN' });
}

function handleGameStarted(payload) {
  if (missionNameEl) missionNameEl.textContent = `MISSION: ${payload.mission_name.toUpperCase()}`;
  if (standbyEl)     standbyEl.style.display   = 'none';
  if (hudEl)         hudEl.style.display        = '';
  gameActive = true;

  resizeCanvas();
  requestAnimationFrame(renderLoop);

  if (payload.briefing_text) {
    showBriefing(payload.mission_name, payload.briefing_text);
  }
}

function handleShipState(payload) {
  shipState = payload;
  if (!gameActive) return;
  updateHUD(payload);
}

function handleWorldEntities(payload) {
  const prev = entities.torpedoes || [];
  entities = payload;

  // Update torpedo trail ring buffers — remove trails for gone torpedoes.
  const currentIds = new Set((entities.torpedoes || []).map(t => t.id));
  for (const id of torpedoTrails.keys()) {
    if (!currentIds.has(id)) torpedoTrails.delete(id);
  }

  // Add current position to each torpedo's trail.
  for (const torp of (entities.torpedoes || [])) {
    if (!torpedoTrails.has(torp.id)) torpedoTrails.set(torp.id, []);
    const trail = torpedoTrails.get(torp.id);
    trail.push({ x: torp.x, y: torp.y });
    if (trail.length > TRAIL_LENGTH) trail.shift();
  }
}

function handleBeamFired(payload) {
  if (!gameActive || !shipState) return;
  beamFlashes.push({
    // Beam source is the ship position at time of fire.
    fromX: shipState.position?.x ?? 50_000,
    fromY: shipState.position?.y ?? 50_000,
    toX:   payload.target_x,
    toY:   payload.target_y,
    startTime: performance.now(),
  });
}

function handleTorpedoHit(payload) {
  if (!gameActive) return;
  torpedoTrails.delete(payload.torpedo_id);
  entities.torpedoes = (entities.torpedoes || []).filter(t => t.id !== payload.torpedo_id);

  // Spawn explosion at hit position (use last known torpedo position).
  if (payload.x !== undefined && payload.y !== undefined) {
    explosions.push({ x: payload.x, y: payload.y, startTime: performance.now() });
  }
}

function handleHullHit(payload) {
  if (!gameActive) return;

  // Screen-edge flash.
  if (flashEl) {
    flashEl.classList.add('active');
    setTimeout(() => flashEl.classList.remove('active'), HIT_FLASH_MS);
  }

  // Shield arc — determine which side was hit from attacker bearing.
  if (payload && payload.attacker_x !== undefined && shipState) {
    const dx = payload.attacker_x - (shipState.position?.x ?? 50_000);
    const dy = payload.attacker_y - (shipState.position?.y ?? 50_000);
    const attackerBearing = Math.atan2(dx, -dy);  // radians, 0=north
    const heading = (shipState.heading ?? 0) * Math.PI / 180;
    const relAngle = attackerBearing - heading;
    shieldArcs.push({ angle: relAngle, startTime: performance.now() });
  }
}

function handleGameOver(payload) {
  gameActive = false;
  const victory = payload.result === 'victory';
  const stats   = payload.stats || {};
  const dur     = stats.duration_s != null
    ? `${Math.floor(stats.duration_s / 60)}:${String(Math.round(stats.duration_s % 60)).padStart(2, '0')}`
    : '—';
  const hull    = stats.hull_remaining != null ? `${Math.round(stats.hull_remaining)}%` : '—';

  if (gameOverTitleEl) gameOverTitleEl.textContent = victory ? 'MISSION COMPLETE' : 'SHIP DESTROYED';
  if (gameOverBodyEl)  gameOverBodyEl.textContent  = `Duration: ${dur}  ·  Hull: ${hull}`;
  if (gameOverEl) {
    gameOverEl.style.display = '';
    // Add Return to Lobby link if not already present.
    if (!gameOverEl.querySelector('.go-btn')) {
      const link = document.createElement('a');
      link.className = 'btn btn--primary go-btn';
      link.href = '/client/lobby/';
      link.textContent = 'RETURN TO LOBBY';
      link.style.cssText = 'display:inline-block;margin-top:1.5rem;';
      gameOverEl.querySelector('.vs-game-over__box')?.appendChild(link);
    }
  }
  if (hudEl) hudEl.style.display = 'none';
}

// ---------------------------------------------------------------------------
// HUD update
// ---------------------------------------------------------------------------

function updateHUD(state) {
  const hull   = Math.max(0, Math.min(100, state.hull ?? 100));
  const shields = state.shields || {};
  const fwd    = Math.max(0, Math.min(100, shields.front ?? 100));
  const aft    = Math.max(0, Math.min(100, shields.rear  ?? 100));
  const hdg    = state.heading ?? 0;

  if (hullFillEl)      hullFillEl.style.width       = `${hull}%`;
  if (hullTextEl)      hullTextEl.textContent        = Math.round(hull);
  if (shieldFwdFillEl) shieldFwdFillEl.style.width   = `${fwd}%`;
  if (shieldFwdTextEl) shieldFwdTextEl.textContent   = Math.round(fwd);
  if (shieldAftFillEl) shieldAftFillEl.style.width   = `${aft}%`;
  if (shieldAftTextEl) shieldAftTextEl.textContent   = Math.round(aft);
  if (hdgTextEl)       hdgTextEl.textContent         = `HDG ${Math.round(hdg).toString().padStart(3,'0')}°`;
}

// ---------------------------------------------------------------------------
// Canvas sizing
// ---------------------------------------------------------------------------

function resizeCanvas() {
  if (!canvas) return;
  canvas.width  = canvas.offsetWidth  || window.innerWidth;
  canvas.height = canvas.offsetHeight || window.innerHeight;
}

// ---------------------------------------------------------------------------
// Render loop
// ---------------------------------------------------------------------------

function renderLoop() {
  if (!gameActive) return;

  // Keep canvas in sync with window size.
  if (canvas.width  !== canvas.offsetWidth ||
      canvas.height !== canvas.offsetHeight) {
    resizeCanvas();
  }

  drawForwardView();
  requestAnimationFrame(renderLoop);
}

// ---------------------------------------------------------------------------
// Forward-view rendering
// ---------------------------------------------------------------------------

function drawForwardView() {
  if (!ctx || !canvas) return;

  const cw = canvas.width;
  const ch = canvas.height;
  const now = performance.now();

  drawBackground(ctx, cw, ch);

  if (!shipState) return;

  const shipX   = shipState.position?.x ?? 50_000;
  const shipY   = shipState.position?.y ?? 50_000;
  const heading = shipState.heading     ?? 0;
  const headRad = heading * Math.PI / 180;

  // Starfield — heading-up parallax.
  drawStarfield(ctx, cw, ch, heading, shipX, shipY, stars);

  // World units per pixel: fit VIEW_RADIUS world units across half the smaller dimension.
  const zoom = VIEW_RADIUS / (Math.min(cw, ch) / 2);

  // Draw everything in heading-up space.
  // Translate to centre then rotate so heading is "up".
  ctx.save();
  ctx.translate(cw / 2, ch / 2);
  ctx.rotate(-headRad);

  // Enemies
  for (const enemy of (entities.enemies || [])) {
    drawEnemy(ctx, enemy, shipX, shipY, zoom, now);
  }

  // Torpedo trails
  for (const torp of (entities.torpedoes || [])) {
    drawTorpedoTrail(ctx, torp, shipX, shipY, zoom, now);
  }

  // Beam flashes
  for (const beam of beamFlashes) {
    drawBeamFlash(ctx, beam, shipX, shipY, zoom, now);
  }

  // Explosions
  for (const exp of explosions) {
    drawExplosion(ctx, exp, shipX, shipY, zoom, now);
  }

  ctx.restore();

  // Shield arcs (screen space, ship at centre)
  for (const arc of shieldArcs) {
    drawShieldArc(ctx, cw, ch, arc, now);
  }

  // Prune expired effects.
  pruneEffects(now);
}

// ---------------------------------------------------------------------------
// World-to-heading-up-canvas transform helper
// Assumes ctx is already translated to (cw/2, ch/2) and rotated by -headRad.
// ---------------------------------------------------------------------------

function worldToHeadingUp(wx, wy, shipX, shipY, zoom) {
  return {
    x: (wx - shipX) / zoom,
    y: (wy - shipY) / zoom,
  };
}

// ---------------------------------------------------------------------------
// Individual draw functions
// ---------------------------------------------------------------------------

function drawEnemy(ctx, enemy, shipX, shipY, zoom, now) {
  const p = worldToHeadingUp(enemy.x, enemy.y, shipX, shipY, zoom);
  const shape = ENEMY_SHAPES[enemy.type] || ENEMY_SHAPES.scout;
  const s = shape.size;

  ctx.save();
  ctx.translate(p.x, p.y);
  // Enemy heading relative to ship heading is already baked in via the
  // canvas rotation; enemy's own orientation is added on top.
  const enemyRelHeadRad = (enemy.heading || 0) * Math.PI / 180;
  ctx.rotate(enemyRelHeadRad);

  ctx.strokeStyle = shape.color;
  ctx.lineWidth   = 1.5;

  if (enemy.type === 'scout') {
    ctx.beginPath();
    ctx.moveTo(0, -s); ctx.lineTo(s, 0); ctx.lineTo(0, s); ctx.lineTo(-s, 0);
    ctx.closePath(); ctx.stroke();
  } else if (enemy.type === 'cruiser') {
    ctx.beginPath();
    ctx.moveTo(0, -s); ctx.lineTo(s, s); ctx.lineTo(-s, s);
    ctx.closePath(); ctx.stroke();
  } else {
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a  = (i * Math.PI) / 3 - Math.PI / 6;
      const px = Math.cos(a) * s;
      const py = Math.sin(a) * s;
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.closePath(); ctx.stroke();
  }

  ctx.restore();

  // Range label — draw at enemy screen position, no additional rotation needed.
  const dist = Math.hypot(enemy.x - shipX, enemy.y - shipY);
  const distKm = (dist / 1000).toFixed(1);
  ctx.fillStyle    = 'rgba(255, 64, 64, 0.5)';
  ctx.font         = '11px "Share Tech Mono", monospace';
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'top';
  ctx.fillText(`${distKm}k`, p.x, p.y + s + 3);
}

function drawTorpedoTrail(ctx, torp, shipX, shipY, zoom, now) {
  const p = worldToHeadingUp(torp.x, torp.y, shipX, shipY, zoom);
  const trail = torpedoTrails.get(torp.id) || [];

  // Draw trail dots from oldest (dim) to newest (bright).
  for (let i = 0; i < trail.length; i++) {
    const tp = worldToHeadingUp(trail[i].x, trail[i].y, shipX, shipY, zoom);
    const alpha = 0.15 + (i / trail.length) * 0.5;
    const radius = 1 + (i / trail.length) * 1.5;
    ctx.beginPath();
    ctx.arc(tp.x, tp.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(0, 255, 65, ${alpha})`;
    ctx.fill();
  }

  // Current torpedo dot — bright.
  ctx.beginPath();
  ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
  ctx.fillStyle = C_PRIMARY;
  ctx.fill();
}

function drawBeamFlash(ctx, beam, shipX, shipY, zoom, now) {
  const elapsed = now - beam.startTime;
  if (elapsed >= BEAM_DURATION) return;

  const t = elapsed / BEAM_DURATION;
  const alpha = 1 - t;

  const from = worldToHeadingUp(beam.fromX, beam.fromY, shipX, shipY, zoom);
  const to   = worldToHeadingUp(beam.toX,   beam.toY,   shipX, shipY, zoom);

  ctx.save();
  ctx.strokeStyle = `rgba(0, 255, 65, ${alpha})`;
  ctx.lineWidth   = 2 - t;
  ctx.beginPath();
  ctx.moveTo(from.x, from.y);
  ctx.lineTo(to.x, to.y);
  ctx.stroke();

  // Bright impact dot at target.
  ctx.beginPath();
  ctx.arc(to.x, to.y, 4 * (1 - t), 0, Math.PI * 2);
  ctx.fillStyle = `rgba(0, 255, 65, ${alpha * 0.8})`;
  ctx.fill();
  ctx.restore();
}

function drawExplosion(ctx, exp, shipX, shipY, zoom, now) {
  const elapsed = now - exp.startTime;
  if (elapsed >= EXPLOSION_DURATION) return;

  const t = elapsed / EXPLOSION_DURATION;
  const p = worldToHeadingUp(exp.x, exp.y, shipX, shipY, zoom);

  // 3 wireframe rings expanding outward.
  const ringData = [
    { startR: 4,  endR: 30, delay: 0    },
    { startR: 8,  endR: 50, delay: 0.1  },
    { startR: 12, endR: 70, delay: 0.2  },
  ];

  for (const ring of ringData) {
    const ringT = Math.max(0, t - ring.delay) / (1 - ring.delay);
    if (ringT <= 0 || ringT > 1) continue;
    const radius = ring.startR + (ring.endR - ring.startR) * ringT;
    const alpha  = 0.9 * (1 - ringT);

    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(0, 255, 65, ${alpha})`;
    ctx.lineWidth   = 1.5 * (1 - ringT * 0.5);
    ctx.stroke();
  }
}

/**
 * Shield arc — drawn in screen space (canvas not rotated).
 * The arc appears on the appropriate edge of the ship position (canvas centre).
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} cw - Canvas width
 * @param {number} ch - Canvas height
 * @param {{angle: number, startTime: number}} arc
 * @param {number} now
 */
function drawShieldArc(ctx, cw, ch, arc, now) {
  const elapsed = now - arc.startTime;
  if (elapsed >= SHIELD_ARC_DURATION) return;

  const t     = elapsed / SHIELD_ARC_DURATION;
  const alpha = 1 - t;
  const cx    = cw / 2;
  const cy    = ch / 2;

  // Arc centred on the attacker direction (arc.angle is relative to heading=up).
  // In screen space the canvas has already been un-rotated, but we're back
  // in the unrotated save()/restore() region. arc.angle is the impact angle
  // in screen space (0 = ahead = top of screen).
  const arcRadius  = 60 + t * 20;
  const arcHalfWidth = Math.PI / 3;  // 60° arc

  ctx.save();
  ctx.beginPath();
  // arc.angle: 0=up (ahead), π/2=right (starboard), π=down (aft), -π/2=left (port)
  // Canvas arc: angle 0=right, so subtract π/2 to align 0=up.
  const canvasAngle = arc.angle - Math.PI / 2;
  ctx.arc(cx, cy, arcRadius, canvasAngle - arcHalfWidth, canvasAngle + arcHalfWidth);
  ctx.strokeStyle = `rgba(0, 160, 255, ${alpha})`;
  ctx.lineWidth   = 3 * (1 - t * 0.5);
  ctx.stroke();
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Effect pruning
// ---------------------------------------------------------------------------

function pruneEffects(now) {
  for (let i = beamFlashes.length - 1; i >= 0; i--) {
    if (now - beamFlashes[i].startTime >= BEAM_DURATION) beamFlashes.splice(i, 1);
  }
  for (let i = explosions.length - 1; i >= 0; i--) {
    if (now - explosions[i].startTime >= EXPLOSION_DURATION) explosions.splice(i, 1);
  }
  for (let i = shieldArcs.length - 1; i >= 0; i--) {
    if (now - shieldArcs[i].startTime >= SHIELD_ARC_DURATION) shieldArcs.splice(i, 1);
  }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
