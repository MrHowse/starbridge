/**
 * Starbridge — Canvas Rendering Utilities
 *
 * Shared drawing functions for the wire aesthetic. All canvas draws use
 * strokeStyle (not fill) except translucent glow hints and background fills.
 *
 * Coordinate systems:
 *   World  — arbitrary units, origin at sector top-left (0,0), x east, y south
 *   Screen — canvas pixels, origin top-left, x right, y down
 *
 * See docs/STYLE_GUIDE.md for full rendering conventions.
 */

// ---------------------------------------------------------------------------
// Colours (matches theme.css CSS custom properties)
// ---------------------------------------------------------------------------

export const C_PRIMARY      = '#00ff41';
export const C_PRIMARY_DIM  = 'rgba(0, 255, 65, 0.3)';
export const C_PRIMARY_GLOW = 'rgba(0, 255, 65, 0.15)';
export const C_FRIENDLY     = '#00aaff';
export const C_BG           = '#0a0a0a';
export const C_GRID         = 'rgba(255, 255, 255, 0.05)';

// ---------------------------------------------------------------------------
// Math helpers (mirrored from server/utils/math_helpers.py)
// ---------------------------------------------------------------------------

/** Linear interpolation. */
export function lerp(a, b, t) {
  return a + (b - a) * t;
}

/**
 * Shortest-path lerp between two angles (degrees).
 * Always travels the short way round the circle.
 */
export function lerpAngle(a, b, t) {
  let diff = ((b - a) % 360 + 360) % 360;
  if (diff > 180) diff -= 360;
  return a + diff * t;
}

// ---------------------------------------------------------------------------
// Coordinate transform
// ---------------------------------------------------------------------------

/**
 * Convert a world position to screen (canvas) pixel coordinates.
 *
 * @param {number} wx - World X
 * @param {number} wy - World Y
 * @param {number} camX - Camera world X (usually ship.x)
 * @param {number} camY - Camera world Y (usually ship.y)
 * @param {number} zoom - World units per pixel
 * @param {number} cw - Canvas width in pixels
 * @param {number} ch - Canvas height in pixels
 * @returns {{x: number, y: number}}
 */
export function worldToScreen(wx, wy, camX, camY, zoom, cw, ch) {
  return {
    x: (wx - camX) / zoom + cw / 2,
    y: (wy - camY) / zoom + ch / 2,
  };
}

// ---------------------------------------------------------------------------
// Starfield
// ---------------------------------------------------------------------------

const STAR_VIRTUAL_SIZE = 2048;  // virtual torus side length (≈ screen pixels)

// Parallax factors per layer: how many virtual units shift per world unit moved.
// Far (0) moves slowest; near (2) moves fastest.
const PARALLAX = [0.08, 0.25, 0.55];

/**
 * Generate a starfield array. Call once; pass the result to drawStarfield.
 * @param {number} count - Number of stars to generate
 * @returns {Array<{x,y,brightness,size,layer}>}
 */
export function createStarfield(count) {
  const V = STAR_VIRTUAL_SIZE;
  const stars = [];
  for (let i = 0; i < count; i++) {
    stars.push({
      x: (Math.random() - 0.5) * V,
      y: (Math.random() - 0.5) * V,
      brightness: Math.random() ** 2, // power curve — mostly dim stars
      size: Math.random() < 0.06 ? 2 : 1,
      layer: Math.floor(Math.random() * 3),
    });
  }
  return stars;
}

/**
 * Draw the background fill. Call first, before any other draw operations.
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} w - Canvas width
 * @param {number} h - Canvas height
 */
export function drawBackground(ctx, w, h) {
  ctx.fillStyle = C_BG;
  ctx.fillRect(0, 0, w, h);
}

/**
 * Draw a parallax starfield on the forward viewscreen.
 *
 * The canvas is rotated so that the ship's heading direction is always "up".
 * Stars parallax with ship position — far stars barely drift, near stars drift
 * noticeably, creating a sense of speed and depth.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} w - Canvas width
 * @param {number} h - Canvas height
 * @param {number} heading - Current ship heading in degrees (0 = north)
 * @param {number} shipX - Ship world X position
 * @param {number} shipY - Ship world Y position
 * @param {Array} stars - From createStarfield()
 */
export function drawStarfield(ctx, w, h, heading, shipX, shipY, stars) {
  const V = STAR_VIRTUAL_SIZE;
  const V_HALF = V / 2;

  ctx.save();
  ctx.translate(w / 2, h / 2);
  // Rotate canvas so heading is "up"; in canvas coords clockwise = positive.
  ctx.rotate(-heading * Math.PI / 180);

  for (const star of stars) {
    const p = PARALLAX[star.layer];

    // Offset star by ship position (parallax), wrap to virtual torus.
    const rx = star.x - shipX * p;
    const ry = star.y - shipY * p;
    const sx = ((rx % V) + V * 1.5) % V - V_HALF;
    const sy = ((ry % V) + V * 1.5) % V - V_HALF;

    const alpha = 0.3 + star.brightness * 0.7;
    // Nearer stars are slightly cooler (blue-shifted) and brighter.
    if (star.size > 1) {
      ctx.fillStyle = `rgba(160, 255, 200, ${alpha})`;
    } else if (star.layer === 2) {
      ctx.fillStyle = `rgba(0, 200, 100, ${alpha})`;
    } else {
      ctx.fillStyle = `rgba(0, 255, 65, ${alpha * (0.45 + star.layer * 0.2)})`;
    }
    ctx.fillRect(sx - star.size / 2, sy - star.size / 2, star.size, star.size);
  }

  ctx.restore();
}

// ---------------------------------------------------------------------------
// Compass dial
// ---------------------------------------------------------------------------

/**
 * Draw a rotating compass card.
 *
 * The card rotates so the current heading is always at the top (12 o'clock).
 * A fixed triangle at the top indicates the ship's forward direction.
 * The target heading is marked by a cyan tick on the rotating ring.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} size - Canvas side length (square)
 * @param {number} currentHeading - Actual ship heading, degrees
 * @param {number} targetHeading - Commanded target heading, degrees
 */
export function drawCompass(ctx, size, currentHeading, targetHeading) {
  const cx = size / 2;
  const cy = size / 2;
  const r  = size / 2 - 10;

  ctx.fillStyle = C_BG;
  ctx.fillRect(0, 0, size, size);

  ctx.save();
  ctx.translate(cx, cy);
  // Rotate ring so current heading is at top.
  ctx.rotate(-currentHeading * Math.PI / 180);

  // Outer ring.
  ctx.strokeStyle = C_PRIMARY_DIM;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(0, 0, r, 0, Math.PI * 2);
  ctx.stroke();

  // Degree tick marks every 5°.
  // In the rotated frame, heading H appears at canvas angle (H - 90) * π/180.
  for (let deg = 0; deg < 360; deg += 5) {
    const rad  = (deg - 90) * Math.PI / 180;
    const isMajor  = deg % 90 === 0;
    const isMedium = deg % 30 === 0;
    const tickLen  = isMajor ? 14 : (isMedium ? 10 : 5);

    ctx.strokeStyle = isMajor ? C_PRIMARY : 'rgba(0, 255, 65, 0.4)';
    ctx.lineWidth   = isMajor ? 2 : 0.75;
    ctx.beginPath();
    ctx.moveTo(Math.cos(rad) * (r - tickLen), Math.sin(rad) * (r - tickLen));
    ctx.lineTo(Math.cos(rad) * r, Math.sin(rad) * r);
    ctx.stroke();

    // Cardinal labels N / E / S / W.
    if (isMajor) {
      const label  = ['N', 'E', 'S', 'W'][deg / 90];
      const textR  = r - 24;
      ctx.fillStyle    = C_PRIMARY;
      ctx.font         = 'bold 11px "Share Tech Mono", monospace';
      ctx.textAlign    = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, Math.cos(rad) * textR, Math.sin(rad) * textR);
    }
  }

  // Target heading tick (cyan, on the rotating ring).
  const tRad = (targetHeading - 90) * Math.PI / 180;
  ctx.strokeStyle = C_FRIENDLY;
  ctx.lineWidth   = 2.5;
  ctx.beginPath();
  ctx.moveTo(Math.cos(tRad) * (r - 16), Math.sin(tRad) * (r - 16));
  ctx.lineTo(Math.cos(tRad) * (r + 2),  Math.sin(tRad) * (r + 2));
  ctx.stroke();

  // Small filled circle at target position.
  ctx.fillStyle = C_FRIENDLY;
  ctx.beginPath();
  ctx.arc(Math.cos(tRad) * (r - 22), Math.sin(tRad) * (r - 22), 3, 0, Math.PI * 2);
  ctx.fill();

  ctx.restore(); // Back to un-rotated screen space.

  // Fixed "ship forward" triangle at top of compass (always at 12 o'clock).
  ctx.fillStyle = C_PRIMARY;
  ctx.beginPath();
  ctx.moveTo(cx, cy - r + 1);       // tip (just inside ring)
  ctx.lineTo(cx - 7, cy - r + 15);  // left
  ctx.lineTo(cx + 7, cy - r + 15);  // right
  ctx.closePath();
  ctx.fill();

  // Current heading readout in centre.
  const hdgStr = Math.round(currentHeading).toString().padStart(3, '0');
  ctx.fillStyle    = C_PRIMARY;
  ctx.font         = '22px "Share Tech Mono", monospace';
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(hdgStr, cx, cy - 8);

  ctx.fillStyle = 'rgba(0, 255, 65, 0.55)';
  ctx.font      = '10px "Share Tech Mono", monospace';
  ctx.fillText('HDG', cx, cy + 12);
}

// ---------------------------------------------------------------------------
// Ship chevron (used on minimap and any overview display)
// ---------------------------------------------------------------------------

/**
 * Draw a wireframe ship chevron at (cx, cy) pointing in headingRad direction.
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} cx - Centre X in canvas pixels
 * @param {number} cy - Centre Y in canvas pixels
 * @param {number} headingRad - Heading in radians (0 = up = north)
 * @param {number} halfSize - Half-size of the chevron in pixels
 * @param {string} colour - CSS colour string
 */
export function drawShipChevron(ctx, cx, cy, headingRad, halfSize, colour) {
  const s = halfSize;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(headingRad);   // rotate so "up" (−y) is the heading direction

  ctx.strokeStyle = colour;
  ctx.lineWidth   = 1.5;
  ctx.beginPath();
  ctx.moveTo(0, -s);             // nose
  ctx.lineTo(s * 0.7, s * 0.7); // right wing tip
  ctx.lineTo(0, s * 0.25);      // centre notch
  ctx.lineTo(-s * 0.7, s * 0.7); // left wing tip
  ctx.closePath();
  ctx.stroke();

  ctx.restore();
}

// ---------------------------------------------------------------------------
// Sector minimap
// ---------------------------------------------------------------------------

const SECTOR_W = 100_000;
const SECTOR_H = 100_000;

/**
 * Draw the sector minimap — a top-down view of the whole sector showing the
 * ship's position and heading.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} size - Canvas side length (square)
 * @param {number} shipX - Ship world X
 * @param {number} shipY - Ship world Y
 * @param {number} heading - Ship heading in degrees
 */
export function drawMinimap(ctx, size, shipX, shipY, heading) {
  ctx.fillStyle = C_BG;
  ctx.fillRect(0, 0, size, size);

  const PAD = 6;
  const mapW = size - PAD * 2;
  const mapH = size - PAD * 2;

  // Sector boundary box.
  ctx.strokeStyle = C_PRIMARY_DIM;
  ctx.lineWidth   = 1;
  ctx.strokeRect(PAD, PAD, mapW, mapH);

  // Faint grid (5×5 cells).
  ctx.strokeStyle = C_GRID;
  ctx.lineWidth   = 0.5;
  for (let i = 1; i < 5; i++) {
    const gx = PAD + (mapW / 5) * i;
    const gy = PAD + (mapH / 5) * i;
    ctx.beginPath(); ctx.moveTo(gx, PAD);      ctx.lineTo(gx, PAD + mapH); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(PAD, gy);      ctx.lineTo(PAD + mapW, gy); ctx.stroke();
  }

  // Ship position (clamped to map area for safety).
  const sx = PAD + Math.max(0, Math.min(1, shipX / SECTOR_W)) * mapW;
  const sy = PAD + Math.max(0, Math.min(1, shipY / SECTOR_H)) * mapH;

  // Heading indicator line behind chevron.
  const headRad = heading * Math.PI / 180;
  const lineLen = 14;
  ctx.strokeStyle = C_PRIMARY_DIM;
  ctx.lineWidth   = 1;
  ctx.beginPath();
  ctx.moveTo(sx, sy);
  ctx.lineTo(sx + Math.sin(headRad) * lineLen, sy - Math.cos(headRad) * lineLen);
  ctx.stroke();

  drawShipChevron(ctx, sx, sy, headRad, 5, C_PRIMARY);

  // Sector corner labels.
  ctx.fillStyle    = 'rgba(0, 255, 65, 0.25)';
  ctx.font         = '8px "Share Tech Mono", monospace';
  ctx.textAlign    = 'left';
  ctx.textBaseline = 'top';
  ctx.fillText('0,0', PAD + 2, PAD + 2);
}
