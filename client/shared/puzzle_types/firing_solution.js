/**
 * Puzzle type: Firing Solution
 *
 * Weapons station — calculate the intercept bearing for a torpedo shot against
 * a moving target.  The puzzle shows a radar-like view with the target's
 * current position and heading arrow.  The player rotates a "firing line"
 * to the bearing they think will intercept the target, then submits.
 *
 * Science assist reveals the target's exact velocity, widening tolerance.
 *
 * Exports the standard puzzle type interface:
 *   init(container, puzzleData)
 *   applyAssist(assistData)
 *   getSubmission()
 *   destroy()
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _container  = null;
let _canvas     = null;
let _ctx        = null;

let _puzzleData = null;    // full puzzle payload from server
let _firingBearing = 0.0; // player's current bearing choice (0–360)
let _dragging  = false;
let _animFrame = 0;        // requestAnimationFrame handle

// Colours
const C = {
  bg:       '#040a04',
  grid:     '#0e1e0e',
  ring:     'rgba(0,255,65,0.15)',
  ship:     '#00ff41',
  target:   '#ff4040',
  heading:  'rgba(255,64,64,0.55)',
  fireLine: '#00c8ff',
  fireZone: 'rgba(0,200,255,0.08)',
  tol:      'rgba(255,204,0,0.18)',
  text:     '#aaffaa',
  textDim:  '#446644',
  label:    '#00ff41',
};

// ---------------------------------------------------------------------------
// Interface
// ---------------------------------------------------------------------------

/**
 * @param {HTMLElement} container
 * @param {Object} puzzleData — { target_bearing, target_distance,
 *                                target_heading, target_velocity,
 *                                torp_velocity, tolerance }
 */
export function init(container, puzzleData) {
  _container  = container;
  _puzzleData = { ...puzzleData };
  _firingBearing = puzzleData.target_bearing;  // default aim toward target

  _buildDOM();
  _animFrame = requestAnimationFrame(_renderLoop);
}

/**
 * Apply Science velocity-data assist.
 * @param {Object} assistData — { target_velocity, target_heading, tolerance }
 */
export function applyAssist(assistData) {
  if (assistData.target_velocity != null) {
    _puzzleData.target_velocity = assistData.target_velocity;
    _puzzleData.target_heading  = assistData.target_heading;
    _puzzleData.tolerance       = assistData.tolerance;
    _updateInfoPanel();
  }
}

/**
 * @returns {{ bearing: number }}
 */
export function getSubmission() {
  return { bearing: Math.round(_firingBearing * 10) / 10 };
}

export function destroy() {
  if (_animFrame) cancelAnimationFrame(_animFrame);
  _animFrame = 0;
  if (_canvas) {
    _canvas.removeEventListener('mousedown', _onMouseDown);
    _canvas.removeEventListener('mousemove', _onMouseMove);
    _canvas.removeEventListener('mouseup',   _onMouseUp);
    _canvas.removeEventListener('touchstart', _onTouchStart);
    _canvas.removeEventListener('touchmove',  _onTouchMove);
    _canvas.removeEventListener('touchend',   _onMouseUp);
  }
  _canvas = null;
  _ctx    = null;
  if (_container) _container.innerHTML = '';
  _container = null;
}

// ---------------------------------------------------------------------------
// DOM construction
// ---------------------------------------------------------------------------

function _buildDOM() {
  _container.innerHTML  = '';
  _container.className  = 'fs-layout';

  // Info panel (data readout)
  const info = document.createElement('div');
  info.className = 'fs-info';
  info.id = 'fs-info-panel';
  _container.appendChild(info);

  // Canvas (radar view)
  _canvas = document.createElement('canvas');
  _canvas.className = 'fs-canvas';
  _container.appendChild(_canvas);

  // Bearing readout
  const brgRow = document.createElement('div');
  brgRow.className = 'fs-bearing-row';
  brgRow.innerHTML = `
    <span class="text-dim text-label">FIRING BRG</span>
    <span class="fs-bearing-val text-data" id="fs-brg-value">${_formatBrg(_firingBearing)}</span>
  `;
  _container.appendChild(brgRow);

  _updateInfoPanel();

  // Canvas interactions.
  _canvas.addEventListener('mousedown', _onMouseDown);
  _canvas.addEventListener('mousemove', _onMouseMove);
  _canvas.addEventListener('mouseup',   _onMouseUp);
  _canvas.addEventListener('touchstart', _onTouchStart, { passive: false });
  _canvas.addEventListener('touchmove',  _onTouchMove,  { passive: false });
  _canvas.addEventListener('touchend',   _onMouseUp);

  // Size canvas.
  _resizeCanvas();
}

function _updateInfoPanel() {
  const panel = document.getElementById('fs-info-panel');
  if (!panel) return;
  const pd  = _puzzleData;
  const vel = pd.target_velocity != null
    ? `${Math.round(pd.target_velocity)} u/s`
    : '<span class="text-dim">UNKNOWN — ASSIST SCIENCE</span>';
  panel.innerHTML = `
    <div class="fs-info-row">
      <span class="fs-label text-label">TARGET BRG</span>
      <span class="fs-value text-data">${_formatBrg(pd.target_bearing)}</span>
    </div>
    <div class="fs-info-row">
      <span class="fs-label text-label">TARGET DIST</span>
      <span class="fs-value text-data">${(pd.target_distance / 1000).toFixed(1)} km</span>
    </div>
    <div class="fs-info-row">
      <span class="fs-label text-label">TARGET HDG</span>
      <span class="fs-value text-data">${_formatBrg(pd.target_heading)}</span>
    </div>
    <div class="fs-info-row">
      <span class="fs-label text-label">TARGET VEL</span>
      <span class="fs-value text-data">${vel}</span>
    </div>
    <div class="fs-info-row">
      <span class="fs-label text-label">TORP VEL</span>
      <span class="fs-value text-data">${Math.round(pd.torp_velocity)} u/s</span>
    </div>
    <div class="fs-info-row">
      <span class="fs-label text-label">TOLERANCE</span>
      <span class="fs-value text-data">±${pd.tolerance.toFixed(1)}°</span>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Render loop
// ---------------------------------------------------------------------------

function _renderLoop() {
  _render();
  _animFrame = requestAnimationFrame(_renderLoop);
}

function _resizeCanvas() {
  if (!_canvas || !_container) return;
  const w = _container.clientWidth || 280;
  const size = Math.min(w, 260);
  _canvas.width  = size;
  _canvas.height = size;
}

function _render() {
  if (!_canvas) return;
  if (_canvas.width !== _canvas.offsetWidth && _canvas.offsetWidth > 0) {
    _resizeCanvas();
  }
  const ctx = _canvas.getContext('2d');
  _ctx = ctx;
  const W   = _canvas.width;
  const H   = _canvas.height;
  const cx  = W / 2;
  const cy  = H / 2;

  // World scale: target_distance → half canvas.
  const maxDist   = (_puzzleData.target_distance || 5000) * 1.35;
  const worldToPx = (Math.min(cx, cy) - 8) / maxDist;

  // Background.
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, W, H);

  // Range rings.
  ctx.strokeStyle = C.ring;
  ctx.lineWidth   = 1;
  for (let r = 1; r <= 3; r++) {
    const pr = (Math.min(cx, cy) - 8) * (r / 3);
    ctx.beginPath();
    ctx.arc(cx, cy, pr, 0, Math.PI * 2);
    ctx.stroke();
  }

  // Tolerance arc (shaded zone around firing line).
  const tol    = _puzzleData.tolerance || 10;
  const tolRad = tol * Math.PI / 180;
  const fireRad = _bearingToRad(_firingBearing);
  const maxR   = Math.min(cx, cy) - 4;

  ctx.save();
  ctx.fillStyle = C.tol;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.arc(cx, cy, maxR, fireRad - tolRad - Math.PI / 2, fireRad + tolRad - Math.PI / 2);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  // Target heading arrow.
  const tBrg   = _puzzleData.target_bearing;
  const tDist  = _puzzleData.target_distance;
  const tx     = cx + Math.sin(tBrg * Math.PI / 180) * tDist * worldToPx;
  const ty     = cy - Math.cos(tBrg * Math.PI / 180) * tDist * worldToPx;
  const tHdgRad = _bearingToRad(_puzzleData.target_heading);
  const arrowLen = 24;

  ctx.save();
  ctx.strokeStyle = C.heading;
  ctx.lineWidth   = 1.5;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(tx, ty);
  ctx.lineTo(tx + Math.sin(tHdgRad) * arrowLen, ty - Math.cos(tHdgRad) * arrowLen);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();

  // Target blip.
  ctx.fillStyle = C.target;
  ctx.beginPath();
  ctx.arc(tx, ty, 5, 0, Math.PI * 2);
  ctx.fill();

  // Target label.
  ctx.fillStyle   = C.target;
  ctx.font        = '8px "Share Tech Mono", monospace';
  ctx.textAlign   = 'center';
  ctx.textBaseline = 'top';
  ctx.fillText('TARGET', tx, ty + 7);

  // Firing line (player's chosen bearing).
  ctx.save();
  ctx.strokeStyle = C.fireLine;
  ctx.lineWidth   = 2;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  const lineX = cx + Math.sin(fireRad) * maxR;
  const lineY = cy - Math.cos(fireRad) * maxR;
  ctx.lineTo(lineX, lineY);
  ctx.stroke();
  ctx.restore();

  // Arrowhead on firing line.
  const ah = 8;
  const ahAngle = Math.PI / 5;
  ctx.save();
  ctx.translate(lineX, lineY);
  ctx.rotate(fireRad);
  ctx.fillStyle = C.fireLine;
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(-ah * Math.sin(ahAngle), -ah * Math.cos(ahAngle));
  ctx.lineTo(ah * Math.sin(ahAngle), -ah * Math.cos(ahAngle));
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  // Ship at centre.
  ctx.save();
  ctx.strokeStyle = C.ship;
  ctx.lineWidth   = 1.5;
  const s = 7;
  ctx.beginPath();
  ctx.moveTo(cx, cy - s);
  ctx.lineTo(cx + s * 0.6, cy + s * 0.6);
  ctx.lineTo(cx, cy + s * 0.2);
  ctx.lineTo(cx - s * 0.6, cy + s * 0.6);
  ctx.closePath();
  ctx.stroke();
  ctx.restore();

  // Firing bearing label near arrowhead.
  ctx.fillStyle    = C.fireLine;
  ctx.font         = '9px "Share Tech Mono", monospace';
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'middle';
  const lblOffset = 14;
  ctx.fillText(
    `${Math.round(_firingBearing).toString().padStart(3,'0')}°`,
    cx + Math.sin(fireRad) * (maxR - lblOffset),
    cy - Math.cos(fireRad) * (maxR - lblOffset),
  );
}

// ---------------------------------------------------------------------------
// Interaction — drag to rotate firing line
// ---------------------------------------------------------------------------

function _bearingToRad(brg) {
  return ((brg - 90) * Math.PI) / 180;
}

function _posToBearing(mx, my) {
  const W  = _canvas.width;
  const H  = _canvas.height;
  const cx = W / 2;
  const cy = H / 2;
  return (Math.atan2(mx - cx, -(my - cy)) * 180 / Math.PI + 360) % 360;
}

function _getCanvasPos(e) {
  const rect = _canvas.getBoundingClientRect();
  const sx   = _canvas.width  / rect.width;
  const sy   = _canvas.height / rect.height;
  return {
    x: (e.clientX - rect.left) * sx,
    y: (e.clientY - rect.top)  * sy,
  };
}

function _onMouseDown(e) {
  _dragging = true;
  const pos = _getCanvasPos(e);
  _setBearing(_posToBearing(pos.x, pos.y));
}

function _onMouseMove(e) {
  if (!_dragging) return;
  const pos = _getCanvasPos(e);
  _setBearing(_posToBearing(pos.x, pos.y));
}

function _onMouseUp() {
  _dragging = false;
}

function _onTouchStart(e) {
  e.preventDefault();
  if (e.touches.length === 0) return;
  _dragging = true;
  const pos = _getCanvasPos(e.touches[0]);
  _setBearing(_posToBearing(pos.x, pos.y));
}

function _onTouchMove(e) {
  e.preventDefault();
  if (!_dragging || e.touches.length === 0) return;
  const pos = _getCanvasPos(e.touches[0]);
  _setBearing(_posToBearing(pos.x, pos.y));
}

function _setBearing(brg) {
  _firingBearing = brg;
  const el = document.getElementById('fs-brg-value');
  if (el) el.textContent = _formatBrg(brg);
}

function _formatBrg(brg) {
  return `${Math.round(brg).toString().padStart(3, '0')}°`;
}
