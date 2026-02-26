/**
 * wireframe.js — 3D wireframe viewport renderer for the Captain station.
 *
 * Four viewports (Forward, Aft, Port, Starboard) each showing a 90° arc of
 * space around the ship. Contacts are rendered as Elite-style vector wireframe
 * ship models using simple perspective projection (canvas 2D, no WebGL).
 *
 * Coordinate conventions:
 *   World: x=east, y=south (increasing y = further south). Heading 0=north.
 *   Camera space: cx=depth (positive = in front of camera),
 *                 cy=lateral (positive = right of camera)
 *   Screen: origin top-left. Screen-y increases downward.
 *   Model vertices: [lateral, depth, vertical] — vertical positive = up on screen.
 */

// ---------------------------------------------------------------------------
// Wireframe model library
// Each model: { verts: [[l,d,v]…], edges: [[i,j]…], scale: worldUnits }
// scale = model's nominal "radius" in world units for perspective calculation.
// ---------------------------------------------------------------------------

const MODEL_SCALE = 1800; // world units for standard model

const WIREFRAME_MODELS = {
  scout: {
    verts: [
      [ 0,  1,  0],   // 0 nose
      [-1, -0.5, 0],  // 1 left wingtip
      [ 1, -0.5, 0],  // 2 right wingtip
      [ 0, -0.4, 0.5],// 3 top fin
      [ 0, -0.6, 0],  // 4 tail
    ],
    edges: [[0,1],[0,2],[1,4],[2,4],[0,3],[3,4]],
    scale: MODEL_SCALE,
  },
  cruiser: {
    verts: [
      [ 0,  1.5, 0],  // 0 nose
      [-1.2, 0, 0],   // 1 left flank
      [ 1.2, 0, 0],   // 2 right flank
      [-0.8,-1.2, 0], // 3 left rear
      [ 0.8,-1.2, 0], // 4 right rear
      [ 0, -1.5, 0],  // 5 tail
      [ 0,  0.5, 0.8],// 6 top turret
      [ 0, -0.5, 0.6],// 7 mid fin
    ],
    edges: [[0,1],[0,2],[1,3],[2,4],[3,5],[4,5],[0,6],[1,6],[2,6],[3,7],[4,7],[5,7]],
    scale: MODEL_SCALE * 1.6,
  },
  destroyer: {
    verts: [
      [ 0,  2, 0],    // 0 nose
      [-0.4, 1, 0.4], // 1 upper-left
      [ 0.4, 1, 0.4], // 2 upper-right
      [-1.5, 0, 0],   // 3 left wing
      [ 1.5, 0, 0],   // 4 right wing
      [-1, -1.5, 0],  // 5 left rear
      [ 1, -1.5, 0],  // 6 right rear
      [ 0, -2,   0],  // 7 tail
      [ 0,  0.5, 1],  // 8 command tower
    ],
    edges: [[0,1],[0,2],[1,2],[1,3],[2,4],[3,5],[4,6],[5,7],[6,7],
            [0,8],[1,8],[2,8],[3,8],[4,8]],
    scale: MODEL_SCALE * 2.2,
  },
  station: {
    verts: [
      [-1,-1, 1],[-1, 1, 1],[ 1, 1, 1],[ 1,-1, 1],  // 0-3 top face
      [-1,-1,-1],[-1, 1,-1],[ 1, 1,-1],[ 1,-1,-1],  // 4-7 bottom face
      [ 0, 2, 0],[ 0,-2, 0],  // 8-9 solar panels
      [ 2, 0, 0],[-2, 0, 0],  // 10-11 dock arms
    ],
    edges: [[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],
            [0,4],[1,5],[2,6],[3,7],[1,8],[2,8],[5,9],[6,9],[2,10],[6,10],[1,11],[5,11]],
    scale: MODEL_SCALE * 3,
  },
  torpedo: {
    verts: [[0,0.3,0],[0,-0.3,0],[0.3,0,0],[-0.3,0,0],[0,0,0.3],[0,0,-0.3]],
    edges: [[0,1],[2,3],[4,5]],
    scale: 400,
  },
  friendly: {
    verts: [
      [ 0, 1, 0],
      [-0.8,-0.5, 0],
      [ 0.8,-0.5, 0],
      [ 0, -0.3, 0.6],
    ],
    edges: [[0,1],[0,2],[1,2],[0,3],[1,3],[2,3]],
    scale: MODEL_SCALE,
  },
};

// ---------------------------------------------------------------------------
// Starfield (static, generated once)
// ---------------------------------------------------------------------------

const STAR_COUNT = 80;
const _stars = Array.from({ length: STAR_COUNT }, (_, i) => ({
  // Distribute stars evenly around the full 360°
  az: (i / STAR_COUNT) * Math.PI * 2 + Math.random() * 0.3,
  el: (Math.random() - 0.5) * 0.8, // ±40° elevation
  brightness: 0.3 + Math.random() * 0.7,
  size: Math.random() < 0.15 ? 2 : 1,
}));

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _canvases = {};  // { forward, aft, port, starboard }
let _ctxs = {};
let _contacts = [];
let _torpedoes = [];
let _ship = null;
let _alertLevel = 'green';
let _hitFlash = { active: false, timer: 0, viewport: null };
let _beamFlash = { active: false, timer: 0 };
let _animHandle = null;
let _shipSilhouetteImg = null;
let _shipClass = '';

// View mode + overlay toggles
let _viewMode = 'quad';         // 'quad' | 'fore' | 'aft' | 'port' | 'starboard'
let _singleCanvas = null;       // canvas element for single-viewport mode
let _singleCtx    = null;
let _highlightsEnabled = false;
let _labelsEnabled     = false;

const VIEWPORT_DIRS = {
  forward:   0,    // degrees offset from heading
  aft:     180,
  port:    -90,
  starboard: 90,
};

const VIEWPORT_LABELS = {
  forward: 'FWD',
  aft:     'AFT',
  port:    'PORT',
  starboard: 'STBD',
};

// Map view-mode key → viewport direction key
const VIEW_MODE_VP = {
  fore:      'forward',
  aft:       'aft',
  port:      'port',
  starboard: 'starboard',
};

// Full labels for single-viewport corner text
const VIEWPORT_FULL_LABELS = {
  forward:   'FORWARD VIEW',
  aft:       'AFT VIEW',
  port:      'PORT VIEW',
  starboard: 'STARBOARD VIEW',
};

const FOV = 220;   // perspective focal length in px
const HALF_ARC = 45; // degrees each side of viewport centre

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Initialise the viewport renderer.
 * @param {{ forward, aft, port, starboard }} canvasMap — canvas elements by viewport
 */
export function initViewports(canvasMap) {
  _canvases = canvasMap;
  for (const [key, canvas] of Object.entries(canvasMap)) {
    _ctxs[key] = canvas.getContext('2d');
    canvas.width  = canvas.parentElement?.clientWidth  || 200;
    canvas.height = canvas.parentElement?.clientHeight || 150;
  }
  _startLoop();
}

export function updateViewportContacts(contacts, torpedoes) {
  _contacts  = contacts  || [];
  _torpedoes = torpedoes || [];
}

export function updateViewportShip(shipState) {
  _ship = shipState;
}

export function updateViewportAlert(level) {
  _alertLevel = level;
}

export function triggerHullHitFlash() {
  _hitFlash.active = true;
  _hitFlash.timer  = 400; // ms
}

export function triggerBeamFlash() {
  _beamFlash.active = true;
  _beamFlash.timer  = 200;
}

export function setViewMode(mode) {
  _viewMode = mode;
}

export function setSingleCanvas(canvas) {
  _singleCanvas = canvas;
  _singleCtx    = canvas ? canvas.getContext('2d') : null;
}

export function setHighlights(on) { _highlightsEnabled = on; }
export function setLabels(on)     { _labelsEnabled     = on; }

/**
 * Load the ship-class silhouette SVG for viewport overlay.
 * @param {string} shipClass — e.g. 'frigate', 'battleship'
 */
export function setShipClass(shipClass) {
  _shipClass = shipClass || '';
  _shipSilhouetteImg = null;
  if (!shipClass) return;
  const img = new Image();
  img.src = `/client/shared/silhouettes/${shipClass}.svg`;
  img.onload = () => { _shipSilhouetteImg = img; };
}

export function resizeViewports() {
  for (const [key, canvas] of Object.entries(_canvases)) {
    canvas.width  = canvas.parentElement?.clientWidth  || 200;
    canvas.height = canvas.parentElement?.clientHeight || 150;
  }
  if (_singleCanvas) {
    _singleCanvas.width  = _singleCanvas.parentElement?.clientWidth  || 400;
    _singleCanvas.height = _singleCanvas.parentElement?.clientHeight || 300;
  }
}

// ---------------------------------------------------------------------------
// Animation loop
// ---------------------------------------------------------------------------

let _lastTs = 0;

function _startLoop() {
  if (_animHandle) cancelAnimationFrame(_animHandle);
  function frame(ts) {
    const dt = ts - _lastTs;
    _lastTs = ts;
    _updateFlash(dt);
    _drawAll();
    _animHandle = requestAnimationFrame(frame);
  }
  _animHandle = requestAnimationFrame(frame);
}

function _updateFlash(dt) {
  if (_hitFlash.active)  { _hitFlash.timer  -= dt; if (_hitFlash.timer  <= 0) _hitFlash.active  = false; }
  if (_beamFlash.active) { _beamFlash.timer -= dt; if (_beamFlash.timer <= 0) _beamFlash.active = false; }
}

function _drawAll() {
  if (_viewMode === 'quad') {
    for (const vp of Object.keys(_canvases)) _drawViewport(vp);
  } else {
    const vpKey = VIEW_MODE_VP[_viewMode];
    if (_singleCanvas && vpKey) _drawViewport(vpKey, _singleCanvas, _singleCtx);
  }
}

// ---------------------------------------------------------------------------
// Per-viewport rendering
// ---------------------------------------------------------------------------

function _drawViewport(vp, canvasOverride = null, ctxOverride = null) {
  const canvas = canvasOverride || _canvases[vp];
  const ctx    = ctxOverride    || _ctxs[vp];
  if (!canvas || !ctx) return;

  const W = canvas.width;
  const H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  // Background
  ctx.fillStyle = '#000004';
  ctx.fillRect(0, 0, W, H);

  // Stars
  _drawStars(ctx, W, H, vp);

  // Grid horizon line
  ctx.strokeStyle = 'rgba(0,50,80,0.5)';
  ctx.lineWidth = 0.5;
  ctx.beginPath(); ctx.moveTo(0, H/2); ctx.lineTo(W, H/2); ctx.stroke();

  // Contacts
  const inQuad = !canvasOverride;
  if (_ship) {
    _drawContacts(ctx, W, H, vp, inQuad);
    _drawTorpedoes(ctx, W, H, vp);
  }

  // Hull-hit flash overlay
  if (_hitFlash.active) {
    const alpha = Math.min(0.4, _hitFlash.timer / 400 * 0.4);
    ctx.fillStyle = `rgba(255,32,32,${alpha})`;
    ctx.fillRect(0, 0, W, H);
  }

  // Beam flash
  if (_beamFlash.active) {
    const alpha = Math.min(0.3, _beamFlash.timer / 200 * 0.3);
    ctx.fillStyle = `rgba(0,200,255,${alpha})`;
    ctx.fillRect(0, 0, W, H);
  }

  // Viewport border — alert-level tint
  const activeBorder = {
    green:  '#00ff41',
    yellow: '#ffb000',
    red:    '#ff2020',
  }[_alertLevel] || '#00aaff';

  ctx.strokeStyle = activeBorder;
  ctx.lineWidth   = _hitFlash.active ? 2 : 1;
  ctx.strokeRect(0.5, 0.5, W - 1, H - 1);

  // Viewport label
  ctx.fillStyle    = activeBorder;
  ctx.textAlign    = 'left';
  ctx.textBaseline = 'top';
  if (canvasOverride) {
    // Single-view mode: larger, more prominent label
    ctx.font = `bold 13px 'Courier New'`;
    ctx.fillText(VIEWPORT_FULL_LABELS[vp], 8, 18);
  } else {
    ctx.font = `bold 10px 'Courier New'`;
    ctx.fillText(VIEWPORT_LABELS[vp], 5, 4);
  }

  // Bearing indicator
  if (_ship) {
    const hdg = Math.round((_ship.heading + VIEWPORT_DIRS[vp] + 360) % 360);
    ctx.font      = `bold 10px 'Courier New'`;
    ctx.textAlign = 'right';
    ctx.fillText(`${String(hdg).padStart(3,'0')}°`, W - 5, 4);
  }

  // Ship silhouette overlay (forward viewport only, bottom-right corner).
  if (vp === 'forward' && _shipSilhouetteImg) {
    const imgH = canvasOverride ? 36 : 24;
    const imgW = imgH * 2;  // SVGs are 200×100 (2:1)
    ctx.save();
    ctx.globalAlpha = 0.25;
    ctx.drawImage(_shipSilhouetteImg, W - imgW - 6, H - imgH - 6, imgW, imgH);
    ctx.restore();
  }
}

// ---------------------------------------------------------------------------
// Starfield
// ---------------------------------------------------------------------------

function _drawStars(ctx, W, H, vp) {
  const hdgRad = _ship ? (_ship.heading + VIEWPORT_DIRS[vp]) * Math.PI / 180 : 0;
  for (const star of _stars) {
    // Project star onto viewport plane
    const relAz = _normaliseAngle(star.az - hdgRad);
    if (Math.abs(relAz) > Math.PI / 2) continue;  // outside ±90° — clip

    const sx = W / 2 + Math.tan(relAz) * FOV * 0.6;
    const sy = H / 2 - Math.tan(star.el) * FOV * 0.6;

    if (sx < 0 || sx > W || sy < 0 || sy > H) continue;

    const alpha = star.brightness;
    ctx.fillStyle = `rgba(200,220,255,${alpha})`;
    ctx.fillRect(sx, sy, star.size, star.size);
  }
}

// ---------------------------------------------------------------------------
// Contacts
// ---------------------------------------------------------------------------

function _drawContacts(ctx, W, H, vp, inQuad = false) {
  const shipX = _ship.position?.x ?? 0;
  const shipY = _ship.position?.y ?? 0;
  const headingRad = (_ship.heading + VIEWPORT_DIRS[vp]) * Math.PI / 180;
  const arcLimit = (HALF_ARC + (inQuad ? 5 : 0)) * Math.PI / 180;

  for (const contact of _contacts) {
    const wx = (contact.x ?? 0) - shipX;
    const wy = (contact.y ?? 0) - shipY;

    const { cx, cy } = _worldToCamera(wx, wy, headingRad);
    if (cx <= 100) continue; // too close / behind camera

    // Arc check
    const bearingAngle = Math.atan2(cy, cx);
    if (Math.abs(bearingAngle) > arcLimit) continue;

    const dist = Math.hypot(wx, wy);

    // Center screen position (used for highlights/labels regardless of wireframe/cross)
    const centerSX = W/2 + cy/cx * FOV;
    const centerSY = H/2;

    const color = _contactColor(contact);
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1;

    // If very distant, draw simple cross instead of full model
    if (dist > 45_000) {
      ctx.beginPath();
      ctx.moveTo(centerSX-4, centerSY); ctx.lineTo(centerSX+4, centerSY);
      ctx.moveTo(centerSX, centerSY-4); ctx.lineTo(centerSX, centerSY+4);
      ctx.stroke();
      if (_highlightsEnabled) _drawContactHighlight(ctx, centerSX, centerSY, dist, contact);
      if (_labelsEnabled)     _drawContactLabel(ctx, centerSX, centerSY, dist, contact);
      continue;
    }

    // Project each edge of the wireframe model
    const modelKey = _contactModelKey(contact);
    const model = WIREFRAME_MODELS[modelKey] || WIREFRAME_MODELS.scout;
    const modelScale = model.scale;
    const { verts, edges } = model;
    const projected = verts.map(([vl, vd, vv]) => {
      const depth   = cx + vd * modelScale / 3000;
      const lateral = cy + vl * modelScale / 3000;
      const vert    = vv * modelScale / 3000;
      if (depth <= 0) return null;
      const s = FOV / depth;
      return { sx: W/2 + lateral * s, sy: H/2 - vert * s, visible: true };
    });

    ctx.beginPath();
    for (const [i, j] of edges) {
      const p = projected[i];
      const q = projected[j];
      if (!p || !q) continue;
      ctx.moveTo(p.sx, p.sy);
      ctx.lineTo(q.sx, q.sy);
    }
    ctx.stroke();

    // Contact label at nose vertex (existing behaviour)
    const p0 = projected[0];
    if (p0) {
      ctx.fillStyle = color;
      ctx.font = '9px "Courier New"';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillText(contact.entity_id || '?', p0.sx, p0.sy - 3);
    }

    if (_highlightsEnabled) _drawContactHighlight(ctx, centerSX, centerSY, dist, contact);
    if (_labelsEnabled)     _drawContactLabel(ctx, centerSX, centerSY, dist, contact);
  }
}

function _drawTorpedoes(ctx, W, H, vp) {
  const shipX = _ship.position?.x ?? 0;
  const shipY = _ship.position?.y ?? 0;
  const headingRad = (_ship.heading + VIEWPORT_DIRS[vp]) * Math.PI / 180;

  for (const torp of _torpedoes) {
    const wx = (torp.x ?? 0) - shipX;
    const wy = (torp.y ?? 0) - shipY;
    const { cx, cy } = _worldToCamera(wx, wy, headingRad);
    if (cx <= 100) continue;
    const bearingAngle = Math.atan2(cy, cx);
    if (Math.abs(bearingAngle) > HALF_ARC * Math.PI / 180) continue;
    const s = FOV / cx;
    const sx = W/2 + cy * s;
    const sy = H/2;
    ctx.fillStyle = '#ffb000';
    ctx.beginPath();
    ctx.arc(sx, sy, 3, 0, Math.PI * 2);
    ctx.fill();
    // Trail
    const tv = _worldToCamera(wx - Math.sin(torp.heading ?? 0) * 500,
                               wy + Math.cos(torp.heading ?? 0) * 500, headingRad);
    if (tv.cx > 100) {
      const ts2 = FOV / tv.cx;
      const tsx = W/2 + tv.cy * ts2;
      ctx.strokeStyle = 'rgba(255,176,0,0.4)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(tsx, sy);
      ctx.stroke();
    }
  }
}

// ---------------------------------------------------------------------------
// Contact highlight + label overlays
// ---------------------------------------------------------------------------

function _highlightStyle(contact) {
  if (contact.type === 'station') {
    return contact.is_friendly
      ? { color: '#40a0ff', lineWidth: 1.5, shape: 'double-circle' }
      : { color: '#ff2020', lineWidth: 1.5, shape: 'double-circle' };
  }
  if (contact.is_friendly) return { color: '#40a0ff', lineWidth: 1.5, shape: 'circle' };
  return                          { color: '#ff4040', lineWidth: 1.5, shape: 'circle' };
}

function _drawContactHighlight(ctx, sx, sy, dist, contact) {
  const r = Math.max(10, 14 + (1 - Math.min(dist, 45_000) / 45_000) * 18);
  const style = _highlightStyle(contact);

  // Pulse alpha for unknown contacts
  let alpha = 1;
  if (contact.classification === 'unknown') {
    alpha = 0.5 + 0.5 * Math.sin(performance.now() / 400);
  }

  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = style.color;
  ctx.lineWidth   = style.lineWidth;
  ctx.beginPath();
  ctx.arc(sx, sy, r, 0, Math.PI * 2);
  ctx.stroke();

  if (style.shape === 'double-circle') {
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(sx, sy, r + 5, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}

function _drawContactLabel(ctx, sx, sy, dist, contact) {
  const r = Math.max(10, 14 + (1 - Math.min(dist, 45_000) / 45_000) * 18);
  const style = _highlightStyle(contact);

  let line1;
  if (contact.classification === 'unknown') {
    line1 = 'UNKNOWN';
  } else if (contact.type === 'station') {
    line1 = 'STATION';
  } else if (contact.is_friendly) {
    line1 = 'FRIENDLY';
  } else {
    line1 = 'HOSTILE';
  }

  const distKm = (dist / 1000).toFixed(1);
  const line2 = `${distKm}km${contact.type ? ' · ' + contact.type.toUpperCase() : ''}`;

  ctx.save();
  ctx.font = '8px "Share Tech Mono",monospace';
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'top';
  ctx.fillStyle = style.color;
  ctx.fillText(line1, sx, sy + r + 2);
  ctx.fillStyle = 'rgba(200,220,255,0.6)';
  ctx.fillText(line2, sx, sy + r + 11);
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Projection helpers
// ---------------------------------------------------------------------------

/**
 * Convert world-relative (dx, dy) into camera-space (cx=depth, cy=lateral).
 * headingRad = camera's heading in game radians (0=north, CW positive).
 * Game convention: north = -y, east = +x.
 * Camera "forward" direction = (sin(h), -cos(h)) in world space.
 */
function _worldToCamera(dx, dy, headingRad) {
  // Rotate world offset into camera space so +cx is "forward".
  const cx =  dx * Math.sin(headingRad) - dy * Math.cos(headingRad);
  const cy =  dx * Math.cos(headingRad) + dy * Math.sin(headingRad);
  return { cx, cy };
}

function _normaliseAngle(a) {
  // Normalise to [-PI, PI]
  while (a >  Math.PI) a -= Math.PI * 2;
  while (a < -Math.PI) a += Math.PI * 2;
  return a;
}

function _contactModelKey(contact) {
  const t = contact.type || '';
  if (t === 'station') return 'station';
  if (t === 'torpedo') return 'torpedo';
  if (contact.is_friendly) return 'friendly';
  if (t === 'destroyer') return 'destroyer';
  if (t === 'cruiser')   return 'cruiser';
  return 'scout';
}

function _contactColor(contact) {
  if (contact.type === 'station') return '#00aaff';
  if (contact.is_friendly) return '#00ff41';
  return '#ff2020';
}
