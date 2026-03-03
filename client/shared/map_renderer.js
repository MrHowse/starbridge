/**
 * Starbridge — MapRenderer
 *
 * A configurable, multi-layer canvas renderer for tactical maps and sensor
 * displays. Replaces per-station canvas duplication.
 *
 * Usage:
 *   const map = new MapRenderer(canvas, { range: 30000, orientation: 'north-up' });
 *   map.updateShipState(payload);
 *   map.updateContacts(contacts, torpedoes);
 *   // In rAF loop:
 *   map.render(now);
 *
 * After render(), the station can draw additional overlays directly on the
 * canvas using map.worldToCanvas() for coordinate transforms.
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const C_BG          = '#0a0a0a';
const C_PRIMARY     = '#00ff41';
const C_PRIMARY_DIM = 'rgba(0, 255, 65, 0.3)';
const C_GRID        = 'rgba(255, 255, 255, 0.05)';
const C_ENEMY       = '#ff4040';
const C_FRIENDLY    = '#00aaff';
const C_RING        = 'rgba(255, 176, 0, 0.18)';

const TRAIL_LENGTH  = 5;

// Enemy wireframe sizes (half-size in canvas pixels).
const ENEMY_SHAPES = {
  scout:     { size: 8  },
  cruiser:   { size: 10 },
  destroyer: { size: 13 },
};

// Hazard rendering config.
const HAZARD_FILL   = {
  nebula:         'rgba(100, 60, 200, 0.18)',
  minefield:      'rgba(255, 80,  40, 0.22)',
  radiation_zone: 'rgba(180, 255, 60, 0.18)',
  gravity_well:   'rgba(60, 180, 255, 0.18)',
};
const HAZARD_STROKE = {
  nebula:         'rgba(140, 80, 255, 0.45)',
  minefield:      'rgba(255, 80, 40,  0.55)',
  radiation_zone: 'rgba(180, 255, 60, 0.45)',
  gravity_well:   'rgba(60, 180, 255, 0.45)',
};

// Damage overlay: impact pulses fade over this duration.
const DAMAGE_FADE_MS = 5000;

// ---------------------------------------------------------------------------
// MapRenderer
// ---------------------------------------------------------------------------

export class MapRenderer {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {object} opts
   * @param {number}  opts.range          - World units visible from centre edge (default 30000)
   * @param {string}  opts.orientation    - 'north-up' | 'heading-up' (default 'north-up')
   * @param {boolean} opts.showGrid       - Draw faint background grid (default true)
   * @param {boolean} opts.showRangeRings - Draw 3 concentric range rings (default true)
   * @param {boolean} opts.interactive    - Enable click-to-select contacts (default false)
   * @param {object}  opts.zoom           - { enabled, min, max } for scroll-wheel zoom
   * @param {function} opts.drawContact   - Custom per-contact renderer:
   *                                        (ctx, sx, sy, contact, selected, now) => void
   *                                        If omitted, uses default wireframe shapes.
   */
  constructor(canvas, opts = {}) {
    this._canvas = canvas;
    this._ctx    = canvas.getContext('2d');

    this._range         = opts.range          ?? 30_000;
    this._orientation   = opts.orientation    ?? 'north-up';
    this._showGrid      = opts.showGrid       ?? true;
    this._showRangeRings = opts.showRangeRings ?? true;
    this._drawContactFn = opts.drawContact    ?? null;

    // Zoom
    this._zoomLevel  = 1.0;
    this._zoomMin    = opts.zoom?.min ?? 0.5;
    this._zoomMax    = opts.zoom?.max ?? 4.0;
    this._zoomEnabled = opts.zoom?.enabled ?? false;
    if (this._zoomEnabled) this._setupZoom();

    // Interaction
    this._interactive        = opts.interactive ?? false;
    this._onContactClickFn   = null;
    this._selectedContactId  = null;
    if (this._interactive) this._setupClick();

    // Data
    this._shipState    = null;
    this._contacts     = [];
    this._torpedoes    = [];
    this._hazards      = [];
    this._commsContacts = [];
    this._torpedoTrails = new Map();

    // Camera override (for sector-centred view — ship drawn at world position).
    this._camOverride = null;

    // Overlays
    this._damageEvents = [];   // { x, y, time }
    this._overlayDamage = false;
    this._beamFlash     = null;  // { sx, sy, tx, ty, time } — screen coords

    // Meaningful range rings (beam/torpedo/sensor).
    this._rangeRingDefs = [];   // [{range, label, style}] in world units

    // Ship silhouette (loaded SVG image).
    this._shipSilhouetteImg = null;
  }

  // ── Public data API ────────────────────────────────────────────────────────

  updateShipState(state) {
    this._shipState = state;
  }

  updateCommsContacts(contacts = []) {
    this._commsContacts = contacts;
  }

  updateContacts(contacts = [], torpedoes = []) {
    this._contacts  = contacts;
    this._torpedoes = torpedoes;

    // Update torpedo trail ring buffers.
    const current = new Set(torpedoes.map(t => t.id));
    for (const id of this._torpedoTrails.keys()) {
      if (!current.has(id)) this._torpedoTrails.delete(id);
    }
    for (const t of torpedoes) {
      if (!this._torpedoTrails.has(t.id)) this._torpedoTrails.set(t.id, []);
      const trail = this._torpedoTrails.get(t.id);
      trail.push({ x: t.x, y: t.y });
      if (trail.length > TRAIL_LENGTH) trail.shift();
    }
  }

  updateHazards(hazards = []) {
    this._hazards = hazards;
  }

  /** Return the last known world position of a torpedo, or null if unknown. */
  getLastTorpedoPosition(torpedoId) {
    const trail = this._torpedoTrails.get(torpedoId);
    if (!trail || trail.length === 0) return null;
    return trail[trail.length - 1];
  }

  /** Set viewport range in world units (does NOT filter contacts). */
  setRange(worldUnits) {
    this._range = worldUnits;
    this._zoomLevel = 1.0;   // reset scroll zoom when range changes
  }

  /**
   * Set meaningful range rings to display.
   * @param {Array<{range: number, label: string, style: string}>} defs
   *   range — world units from ship
   *   label — e.g. 'BEAM', 'TORP', 'SENSOR'
   *   style — 'dotted' | 'dashed' | 'solid'
   */
  setRangeRings(defs) {
    this._rangeRingDefs = defs;
  }

  /**
   * Load a ship-class silhouette SVG for the player ship icon.
   * Falls back to chevron if the image fails to load.
   * @param {string} shipClass — e.g. 'frigate', 'battleship'
   */
  loadShipSilhouette(shipClass) {
    this._shipSilhouetteImg = null;
    if (!shipClass) return;
    const img = new Image();
    img.src = `/client/shared/silhouettes/${shipClass}.svg`;
    img.onload = () => { this._shipSilhouetteImg = img; };
  }

  // ── Damage overlay ─────────────────────────────────────────────────────────

  addDamageEvent(wx, wy) {
    this._damageEvents.push({ x: wx, y: wy, time: performance.now() });
  }

  setDamageOverlay(enabled) {
    this._overlayDamage = enabled;
  }

  toggleDamageOverlay() {
    this._overlayDamage = !this._overlayDamage;
  }

  // ── Beam flash (weapons layer) ─────────────────────────────────────────────

  /** Record a beam hit — provide world coordinates. */
  setBeamFlash(wx, wy) {
    this._beamFlash = { wx, wy, time: performance.now() };
  }

  clearBeamFlash() {
    this._beamFlash = null;
  }

  // ── Camera override (sector mode) ──────────────────────────────────────────

  /**
   * Override the camera origin. When set, worldToCanvas() uses (x,y) as the
   * map centre instead of the ship position, and the ship is drawn as a small
   * icon at its actual world location rather than at the canvas centre.
   */
  setCameraOverride(x, y) { this._camOverride = { x, y }; }

  /** Restore default ship-centred camera. */
  clearCameraOverride()    { this._camOverride = null; }

  /** @private Return the current camera world position. */
  _getCamPos() {
    if (this._camOverride) return this._camOverride;
    return {
      x: this._shipState?.position?.x ?? 50_000,
      y: this._shipState?.position?.y ?? 50_000,
    };
  }

  // ── Selection ──────────────────────────────────────────────────────────────

  selectContact(id) {
    this._selectedContactId = id;
  }

  onContactClick(fn) {
    this._onContactClickFn = fn;
  }

  // ── Coordinate transform (public, for station overlay draws) ───────────────

  /**
   * Convert a world position to canvas pixel coordinates.
   * Uses the camera origin (ship position, or override if set).
   */
  worldToCanvas(wx, wy) {
    if (!this._shipState) return { x: 0, y: 0 };
    const cw  = this._canvas.width;
    const ch  = this._canvas.height;
    const cam = this._getCamPos();
    const zoom = this._effectiveZoom(cw, ch);
    return {
      x: cw / 2 + (wx - cam.x) / zoom,
      y: ch / 2 + (wy - cam.y) / zoom,
    };
  }

  /** World units per canvas pixel at current zoom. */
  getZoom() {
    const cw = this._canvas.width;
    const ch = this._canvas.height;
    return this._effectiveZoom(cw, ch);
  }

  // ── Rendering ──────────────────────────────────────────────────────────────

  render(now = performance.now()) {
    const canvas = this._canvas;
    const ctx    = this._ctx;

    // Auto-resize canvas to CSS size.
    const rect = canvas.getBoundingClientRect();
    if (rect.width > 0 && (canvas.width !== Math.round(rect.width) || canvas.height !== Math.round(rect.height))) {
      canvas.width  = Math.round(rect.width);
      canvas.height = Math.round(rect.height);
    }

    const cw = canvas.width;
    const ch = canvas.height;

    // Background.
    ctx.fillStyle = C_BG;
    ctx.fillRect(0, 0, cw, ch);

    if (!this._shipState) return;

    const cam     = this._getCamPos();
    const camX    = cam.x;
    const camY    = cam.y;
    const heading = this._shipState.heading ?? 0;
    const zoom    = this._effectiveZoom(cw, ch);

    // For heading-up orientation, rotate canvas so ship forward is always up.
    const isHeadingUp = this._orientation === 'heading-up';
    if (isHeadingUp) {
      ctx.save();
      ctx.translate(cw / 2, ch / 2);
      ctx.rotate(-heading * Math.PI / 180);
      ctx.translate(-cw / 2, -ch / 2);
    }

    // Layers.
    if (this._showGrid)       this._drawGrid(ctx, cw, ch, camX, camY, zoom);
    if (this._showRangeRings) this._drawRangeRings(ctx, cw, ch);
    if (this._hazards.length) this._drawHazards(ctx, cw, ch, camX, camY, zoom);
    this._drawTorpedoes(ctx, cw, ch, camX, camY, zoom, now);
    this._drawCommsContacts(ctx, cw, ch, camX, camY, zoom, now);
    this._drawContacts(ctx, cw, ch, camX, camY, zoom, now);

    if (isHeadingUp) ctx.restore();

    // Ship position in canvas coords.
    const shipWX = this._shipState.position?.x ?? 50_000;
    const shipWY = this._shipState.position?.y ?? 50_000;
    const headRad = heading * Math.PI / 180;

    if (this._camOverride) {
      // Camera-override mode (e.g. sector view): draw ship as small icon at world position.
      const sp = this.worldToCanvas(shipWX, shipWY);
      if (sp.x >= -10 && sp.x <= cw + 10 && sp.y >= -10 && sp.y <= ch + 10) {
        _drawShipIcon(ctx, sp.x, sp.y, headRad, 5, C_PRIMARY, this._shipSilhouetteImg);
      }
    } else {
      // Default: ship icon at canvas centre.
      const chevRot = isHeadingUp ? 0 : headRad;
      _drawShipIcon(ctx, cw / 2, ch / 2, chevRot, 8, C_PRIMARY, this._shipSilhouetteImg);
    }

    // Ship screen position for beam flash origin.
    const shipSx = this._camOverride ? this.worldToCanvas(shipWX, shipWY).x : cw / 2;
    const shipSy = this._camOverride ? this.worldToCanvas(shipWX, shipWY).y : ch / 2;

    // Beam flash (world coords).
    if (this._beamFlash) {
      const BEAM_FLASH_MS = 300;
      const age = now - this._beamFlash.time;
      if (age < BEAM_FLASH_MS) {
        const alpha = (1 - age / BEAM_FLASH_MS) * 0.85;
        const sp    = this.worldToCanvas(this._beamFlash.wx, this._beamFlash.wy);
        ctx.strokeStyle = `rgba(0, 255, 65, ${alpha})`;
        ctx.lineWidth   = 2;
        ctx.beginPath();
        ctx.moveTo(shipSx, shipSy);
        ctx.lineTo(sp.x, sp.y);
        ctx.stroke();
      } else {
        this._beamFlash = null;
      }
    }

    // Damage overlay.
    if (this._overlayDamage) {
      this._drawDamageOverlay(ctx, cw, ch, camX, camY, zoom, now);
    }

    // Range readout + contact count.
    const km = Math.round((this._range * this._zoomLevel) / 1000);
    ctx.fillStyle    = 'rgba(0, 255, 65, 0.45)';
    ctx.font         = '9px "Share Tech Mono", monospace';
    ctx.textAlign    = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillText(`RANGE: ${km}km`, cw - 6, ch - 4);
    // Contact count (diagnostic).
    const nContacts = this._contacts.length;
    const nTorpedoes = this._torpedoes.length;
    if (nContacts > 0 || nTorpedoes > 0) {
      ctx.textAlign    = 'left';
      ctx.fillStyle    = 'rgba(255, 64, 64, 0.6)';
      ctx.fillText(`CONTACTS: ${nContacts}  TORP: ${nTorpedoes}`, 6, ch - 4);
    }
  }

  // ── Private draw helpers ───────────────────────────────────────────────────

  _effectiveZoom(cw, ch) {
    // World units per canvas pixel.
    const halfMin = Math.min(cw, ch) / 2;
    return (this._range * this._zoomLevel) / halfMin;
  }

  _drawGrid(ctx, cw, ch, camX, camY, zoom) {
    // Adaptive grid spacing: choose a round number that gives ~6-10 lines.
    const worldWidth  = cw * zoom;
    const rawStep     = worldWidth / 8;
    const magnitude   = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const GRID_STEP   = Math.ceil(rawStep / magnitude) * magnitude;

    ctx.strokeStyle = C_GRID;
    ctx.lineWidth   = 0.5;

    const xStart = Math.floor((camX - worldWidth / 2) / GRID_STEP) * GRID_STEP;
    const xEnd   = camX + worldWidth / 2 + GRID_STEP;
    for (let wx = xStart; wx <= xEnd; wx += GRID_STEP) {
      const sx = cw / 2 + (wx - camX) / zoom;
      ctx.beginPath();
      ctx.moveTo(sx, 0);
      ctx.lineTo(sx, ch);
      ctx.stroke();
    }

    const worldHeight = ch * zoom;
    const yStart = Math.floor((camY - worldHeight / 2) / GRID_STEP) * GRID_STEP;
    const yEnd   = camY + worldHeight / 2 + GRID_STEP;
    for (let wy = yStart; wy <= yEnd; wy += GRID_STEP) {
      const sy = ch / 2 + (wy - camY) / zoom;
      ctx.beginPath();
      ctx.moveTo(0, sy);
      ctx.lineTo(cw, sy);
      ctx.stroke();
    }
  }

  _drawRangeRings(ctx, cw, ch) {
    const cx = cw / 2;
    const cy = ch / 2;
    const zoom = this._effectiveZoom(cw, ch);

    // If meaningful range ring defs are set, draw those instead.
    if (this._rangeRingDefs.length > 0) {
      for (const def of this._rangeRingDefs) {
        const r = def.range / zoom;
        // Skip rings too small (< 12px) or too large (> 3× canvas).
        if (r < 12 || r > Math.max(cw, ch) * 3) continue;

        ctx.save();
        if (def.style === 'dotted')      ctx.setLineDash([2, 4]);
        else if (def.style === 'dashed') ctx.setLineDash([6, 4]);
        ctx.strokeStyle = C_RING;
        ctx.lineWidth   = 0.8;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);

        // Label at top of ring.
        const labelY = cy - r - 3;
        if (labelY > 4) {
          ctx.fillStyle    = 'rgba(255, 176, 0, 0.4)';
          ctx.font         = '8px "Share Tech Mono", monospace';
          ctx.textAlign    = 'center';
          ctx.textBaseline = 'bottom';
          ctx.fillText(def.label, cx, labelY);
        }
        ctx.restore();
      }
      return;
    }

    // Default: 3 concentric rings at 1/3 intervals.
    const halfMin = Math.min(cw, ch) / 2;
    ctx.strokeStyle = C_RING;
    ctx.lineWidth   = 1;
    for (let i = 1; i <= 3; i++) {
      const r = halfMin * (i / 3);
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  _drawHazards(ctx, cw, ch, camX, camY, zoom) {
    ctx.save();
    for (const hz of this._hazards) {
      const sx = cw / 2 + (hz.x - camX) / zoom;
      const sy = ch / 2 + (hz.y - camY) / zoom;
      const sr = hz.radius / zoom;

      ctx.beginPath();
      ctx.arc(sx, sy, sr, 0, Math.PI * 2);
      ctx.fillStyle   = HAZARD_FILL[hz.hazard_type]   || 'rgba(255,255,255,0.1)';
      ctx.strokeStyle = HAZARD_STROKE[hz.hazard_type] || 'rgba(255,255,255,0.3)';
      ctx.lineWidth   = 0.8;
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  }

  _drawTorpedoes(ctx, cw, ch, camX, camY, zoom, now) {
    for (const torp of this._torpedoes) {
      const trail = this._torpedoTrails.get(torp.id) || [];
      for (let i = 0; i < trail.length - 1; i++) {
        const alpha = (i + 1) / trail.length * 0.5;
        const sx = cw / 2 + (trail[i].x - camX) / zoom;
        const sy = ch / 2 + (trail[i].y - camY) / zoom;
        ctx.fillStyle = `rgba(0, 170, 255, ${alpha})`;
        ctx.beginPath();
        ctx.arc(sx, sy, 2, 0, Math.PI * 2);
        ctx.fill();
      }
      const sx = cw / 2 + (torp.x - camX) / zoom;
      const sy = ch / 2 + (torp.y - camY) / zoom;
      ctx.fillStyle = C_FRIENDLY;
      ctx.beginPath();
      ctx.arc(sx, sy, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  _drawCommsContacts(ctx, cw, ch, camX, camY, zoom, now) {
    const MARGIN = 20;
    for (const cc of this._commsContacts) {
      const px = cc.position?.[0] ?? 0;
      const py = cc.position?.[1] ?? 0;
      const sx = cw / 2 + (px - camX) / zoom;
      const sy = ch / 2 + (py - camY) / zoom;
      const onScreen = sx >= -MARGIN && sx <= cw + MARGIN && sy >= -MARGIN && sy <= ch + MARGIN;

      if (onScreen) {
        _drawCommsContact(ctx, sx, sy, cc, zoom, now);
      } else {
        _drawCommsOffScreenArrow(ctx, cw, ch, sx, sy, cc, this._shipState);
      }
    }
  }

  _drawContacts(ctx, cw, ch, camX, camY, zoom, now) {
    const MARGIN = 20;
    const priorityId = this._shipState?.captain_priority_target ?? null;
    for (const contact of this._contacts) {
      const sx       = cw / 2 + (contact.x - camX) / zoom;
      const sy       = ch / 2 + (contact.y - camY) / zoom;
      const selected = contact.id === this._selectedContactId;
      const onScreen = sx >= -MARGIN && sx <= cw + MARGIN && sy >= -MARGIN && sy <= ch + MARGIN;

      if (onScreen) {
        if (this._drawContactFn) {
          this._drawContactFn(ctx, sx, sy, contact, selected, now);
        } else {
          _drawDefaultContact(ctx, sx, sy, contact, selected);
        }
        // C.1.1: Priority target diamond overlay.
        if (contact.id === priorityId) {
          this._drawPriorityDiamond(ctx, sx, sy, now);
        }
      } else {
        // Off-screen indicator: arrow at canvas edge pointing toward contact.
        _drawOffScreenArrow(ctx, cw, ch, sx, sy, contact, this._shipState);
      }
    }
  }

  /** Draw a pulsing gold diamond around the captain's priority target. */
  _drawPriorityDiamond(ctx, sx, sy, now) {
    const pulse = 0.6 + 0.4 * Math.sin(now / 400);
    const size = 14 + 2 * Math.sin(now / 600);
    ctx.save();
    ctx.strokeStyle = `rgba(255, 215, 0, ${pulse})`;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(sx, sy - size);
    ctx.lineTo(sx + size, sy);
    ctx.lineTo(sx, sy + size);
    ctx.lineTo(sx - size, sy);
    ctx.closePath();
    ctx.stroke();
    // Label
    ctx.fillStyle = `rgba(255, 215, 0, ${pulse})`;
    ctx.font = 'bold 9px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('PRIORITY', sx, sy - size - 4);
    ctx.restore();
  }

  _drawDamageOverlay(ctx, cw, ch, camX, camY, zoom, now) {
    const alive = [];
    for (const ev of this._damageEvents) {
      const age = now - ev.time;
      if (age >= DAMAGE_FADE_MS) continue;
      alive.push(ev);

      const t     = age / DAMAGE_FADE_MS;
      const alpha = (1 - t) * 0.8;
      const sx    = cw / 2 + (ev.x - camX) / zoom;
      const sy    = ch / 2 + (ev.y - camY) / zoom;

      for (let ring = 0; ring < 3; ring++) {
        const ringT  = Math.min(1, t + ring * 0.1);
        const radius = ringT * 24 + 4;
        ctx.save();
        ctx.strokeStyle = `rgba(255, 64, 64, ${alpha * (1 - ring * 0.25)})`;
        ctx.lineWidth   = 1.5;
        ctx.beginPath();
        ctx.arc(sx, sy, radius, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }
    }
    this._damageEvents = alive;
  }

  // ── Zoom ───────────────────────────────────────────────────────────────────

  _setupZoom() {
    this._canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const factor = e.deltaY > 0 ? 1.15 : 0.87;
      this._zoomLevel = Math.max(this._zoomMin, Math.min(this._zoomMax, this._zoomLevel * factor));
    }, { passive: false });
  }

  // ── Click-to-select ────────────────────────────────────────────────────────

  _setupClick() {
    this._canvas.addEventListener('click', (e) => {
      if (!this._shipState || !this._onContactClickFn) return;

      const rect  = this._canvas.getBoundingClientRect();
      const scaleX = this._canvas.width  / rect.width;
      const scaleY = this._canvas.height / rect.height;
      const mx = (e.clientX - rect.left) * scaleX;
      const my = (e.clientY - rect.top)  * scaleY;

      const cw   = this._canvas.width;
      const ch   = this._canvas.height;
      const cam  = this._getCamPos();
      const camX = cam.x;
      const camY = cam.y;
      const zoom = this._effectiveZoom(cw, ch);

      const HIT_R = 18;
      let hit = null;
      for (const contact of this._contacts) {
        const sx = cw / 2 + (contact.x - camX) / zoom;
        const sy = ch / 2 + (contact.y - camY) / zoom;
        const dx = mx - sx;
        const dy = my - sy;
        if (dx * dx + dy * dy <= HIT_R * HIT_R) { hit = contact; break; }
      }
      this._onContactClickFn(hit ? hit.id : null);
    });
  }
}

// ---------------------------------------------------------------------------
// Private draw utilities
// ---------------------------------------------------------------------------

/** Default enemy wireframe (diamond/triangle/hexagon by type). */
function _drawDefaultContact(ctx, sx, sy, contact, selected) {
  const shape = ENEMY_SHAPES[contact.type] || ENEMY_SHAPES.cruiser;
  const s     = shape.size;
  const headRad = (contact.heading || 0) * Math.PI / 180;

  // Bright centre dot — always visible regardless of zoom.
  ctx.fillStyle = C_ENEMY;
  ctx.beginPath();
  ctx.arc(sx, sy, 3, 0, Math.PI * 2);
  ctx.fill();

  ctx.save();
  ctx.translate(sx, sy);
  ctx.rotate(headRad);
  ctx.strokeStyle = C_ENEMY;
  ctx.lineWidth   = selected ? 2 : 1.5;

  if (contact.type === 'scout') {
    ctx.beginPath();
    ctx.moveTo(0, -s); ctx.lineTo(s, 0);
    ctx.lineTo(0, s);  ctx.lineTo(-s, 0);
    ctx.closePath(); ctx.stroke();
  } else if (contact.type === 'cruiser') {
    ctx.beginPath();
    ctx.moveTo(0, -s);
    ctx.lineTo(s * 0.866, s * 0.5);
    ctx.lineTo(-s * 0.866, s * 0.5);
    ctx.closePath(); ctx.stroke();
  } else {
    // Hexagon (destroyer + unknown).
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = (i * Math.PI) / 3 - Math.PI / 6;
      if (i === 0) ctx.moveTo(Math.cos(a) * s, Math.sin(a) * s);
      else         ctx.lineTo(Math.cos(a) * s, Math.sin(a) * s);
    }
    ctx.closePath(); ctx.stroke();
  }

  // Selected: outer glow ring.
  if (selected) {
    ctx.strokeStyle = C_PRIMARY;
    ctx.lineWidth   = 1;
    ctx.beginPath();
    ctx.arc(0, 0, s + 6, 0, Math.PI * 2);
    ctx.stroke();
  }

  ctx.restore();

  // Entity ID label.
  ctx.fillStyle    = 'rgba(255, 64, 64, 0.6)';
  ctx.font         = '9px "Share Tech Mono", monospace';
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'top';
  ctx.fillText(contact.id, sx, sy + s + 2);
}

/** Arrow indicator at canvas edge for off-screen contacts, with distance label. */
function _drawOffScreenArrow(ctx, cw, ch, sx, sy, contact, shipState) {
  const cx = cw / 2;
  const cy = ch / 2;
  const dx = sx - cx;
  const dy = sy - cy;
  const dist = Math.hypot(dx, dy);
  if (dist < 1) return;

  // Colour by classification.
  const cls = contact.classification || 'hostile';
  const CLS_COLORS = { hostile: '#ff4040', unknown: '#ffffff', friendly: '#00ff41', neutral: '#ffaa00' };
  const color = CLS_COLORS[cls] || C_ENEMY;

  // Clamp to canvas edge with margin.
  const M = 20;
  const scale = Math.min(
    (cw / 2 - M) / Math.abs(dx || 1),
    (ch / 2 - M) / Math.abs(dy || 1),
  );
  const ax = cx + dx * scale;
  const ay = cy + dy * scale;
  const angle = Math.atan2(dy, dx);

  ctx.save();
  ctx.translate(ax, ay);
  ctx.rotate(angle);
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.8;
  // Small triangle pointing outward.
  ctx.beginPath();
  ctx.moveTo(7, 0);
  ctx.lineTo(-4, -5);
  ctx.lineTo(-4, 5);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  // Distance label next to the arrow.
  if (shipState?.position) {
    const worldDist = Math.hypot(
      contact.x - shipState.position.x,
      contact.y - shipState.position.y,
    );
    const km = (worldDist / 1000).toFixed(0);
    // Position label just inside the arrow.
    const lx = ax - Math.cos(angle) * 14;
    const ly = ay - Math.sin(angle) * 14;
    ctx.save();
    ctx.fillStyle    = color;
    ctx.globalAlpha  = 0.7;
    ctx.font         = '8px "Share Tech Mono", monospace';
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(`${km}km`, lx, ly);
    ctx.restore();
  }
}

// ---------------------------------------------------------------------------
// Comms contact rendering (intelligence overlay — dashed/outlined)
// ---------------------------------------------------------------------------

const CC_COLORS = {
  distress: '#ff8800',  // orange
  hostile:  '#ff4040',  // red
  friendly: '#00ff41',  // green
  neutral:  '#ffaa00',  // amber
  unknown:  '#ffffff',  // white
};
const CC_ICONS = {
  ship:    'diamond',
  station: 'square',
  hazard:  'region',
  fleet:   'triangle',
  convoy:  'diamond',
  debris:  'region',
  anomaly: 'circle',
  unknown: 'circle',
  data:    'circle',
};

function _drawCommsContact(ctx, sx, sy, cc, zoom, now) {
  const threat = cc.threat_level || 'unknown';
  const color  = CC_COLORS[threat] || CC_COLORS.unknown;
  const icon   = CC_ICONS[cc.entity_type] || CC_ICONS.unknown;
  const merged = !!cc.merged_sensor_id;
  const conf   = cc.confidence || 'unverified';

  // Unverified/rumour contacts pulse
  let alpha = 1.0;
  if (conf === 'unverified' || conf === 'rumour') {
    alpha = 0.4 + 0.4 * Math.sin(now * 0.004);
  }

  ctx.save();
  ctx.globalAlpha = alpha;

  // Uncertainty radius circle (dashed)
  const radius = cc.position_radius || 0;
  if (radius > 0 && !merged) {
    const screenRadius = radius / zoom;
    if (screenRadius > 2) {
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.globalAlpha = alpha * 0.3;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.arc(sx, sy, screenRadius, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    }
  }

  // Icon — dashed outline unless merged with sensor (then solid)
  const s = 7;
  ctx.strokeStyle = color;
  ctx.lineWidth = merged ? 2 : 1.5;
  if (!merged) ctx.setLineDash([3, 3]);

  if (icon === 'diamond') {
    ctx.beginPath();
    ctx.moveTo(sx, sy - s); ctx.lineTo(sx + s, sy);
    ctx.lineTo(sx, sy + s); ctx.lineTo(sx - s, sy);
    ctx.closePath(); ctx.stroke();
  } else if (icon === 'square') {
    ctx.strokeRect(sx - s, sy - s, s * 2, s * 2);
  } else if (icon === 'triangle') {
    ctx.beginPath();
    ctx.moveTo(sx, sy - s);
    ctx.lineTo(sx + s * 0.866, sy + s * 0.5);
    ctx.lineTo(sx - s * 0.866, sy + s * 0.5);
    ctx.closePath(); ctx.stroke();
  } else if (icon === 'region') {
    // Filled translucent region
    const regionR = (radius > 0 ? radius / zoom : 12);
    ctx.fillStyle = color.replace(')', ', 0.12)').replace('rgb', 'rgba');
    ctx.beginPath();
    ctx.arc(sx, sy, Math.max(regionR, 8), 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  } else {
    // Circle (anomaly, unknown, data)
    ctx.beginPath();
    ctx.arc(sx, sy, s, 0, Math.PI * 2);
    ctx.stroke();
  }

  ctx.setLineDash([]);

  // Centre dot
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(sx, sy, 2, 0, Math.PI * 2);
  ctx.fill();

  // "INTEL" label (unless merged)
  const labelY = sy + s + 3;
  ctx.font = '7px "Share Tech Mono", monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  if (merged) {
    ctx.fillStyle = '#00ff41';
    ctx.fillText('CONFIRMED', sx, labelY);
  } else {
    ctx.fillStyle = color;
    ctx.globalAlpha = alpha * 0.7;
    ctx.fillText('INTEL', sx, labelY);
  }

  // Contact name below INTEL label
  if (cc.name && cc.name !== 'Unknown Contact') {
    ctx.globalAlpha = alpha * 0.5;
    ctx.fillText(cc.name, sx, labelY + 9);
  }

  // "?" overlay for unverified/rumour
  if (conf === 'unverified' || conf === 'rumour') {
    ctx.font = 'bold 10px "Share Tech Mono", monospace';
    ctx.fillStyle = color;
    ctx.globalAlpha = alpha;
    ctx.fillText('?', sx, sy - s - 8);
  }

  // Distress icon: pulsing triangle
  if (cc.icon === 'distress') {
    const pulse = 0.7 + 0.3 * Math.sin(now * 0.006);
    ctx.globalAlpha = pulse;
    ctx.fillStyle = CC_COLORS.distress;
    ctx.font = 'bold 10px "Share Tech Mono", monospace';
    ctx.fillText('\u26A0', sx + s + 3, sy - 2);
  }

  ctx.restore();
}

function _drawCommsOffScreenArrow(ctx, cw, ch, sx, sy, cc, shipState) {
  const cx = cw / 2;
  const cy = ch / 2;
  const dx = sx - cx;
  const dy = sy - cy;
  const dist = Math.hypot(dx, dy);
  if (dist < 1) return;

  const threat = cc.threat_level || 'unknown';
  const color = CC_COLORS[threat] || CC_COLORS.unknown;

  const M = 20;
  const scale = Math.min(
    (cw / 2 - M) / Math.abs(dx || 1),
    (ch / 2 - M) / Math.abs(dy || 1),
  );
  const ax = cx + dx * scale;
  const ay = cy + dy * scale;
  const angle = Math.atan2(dy, dx);

  ctx.save();
  ctx.translate(ax, ay);
  ctx.rotate(angle);
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  ctx.globalAlpha = 0.7;
  // Dashed triangle (distinct from sensor contact solid arrows)
  ctx.beginPath();
  ctx.moveTo(7, 0);
  ctx.lineTo(-4, -5);
  ctx.lineTo(-4, 5);
  ctx.closePath();
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();

  // Distance + name label
  if (shipState?.position) {
    const px = cc.position?.[0] ?? 0;
    const py = cc.position?.[1] ?? 0;
    const worldDist = Math.hypot(px - shipState.position.x, py - shipState.position.y);
    const km = (worldDist / 1000).toFixed(0);
    const label = cc.icon === 'distress'
      ? `\u26A0 ${cc.name || 'Distress'} — ${km}km`
      : `${cc.name || 'INTEL'} — ${km}km`;

    const lx = ax - Math.cos(angle) * 14;
    const ly = ay - Math.sin(angle) * 14;
    ctx.save();
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.6;
    ctx.font = '7px "Share Tech Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, lx, ly - 6);
    ctx.restore();
  }
}

/**
 * Draw the player ship icon — uses silhouette SVG if loaded, falls back to chevron.
 */
function _drawShipIcon(ctx, cx, cy, headingRad, halfSize, colour, silhouetteImg) {
  if (silhouetteImg) {
    const imgH = halfSize * 2.5;
    const imgW = imgH * 2;  // SVGs are 200×100 (2:1 aspect)
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(headingRad);
    ctx.globalAlpha = 0.8;
    ctx.drawImage(silhouetteImg, -imgW / 2, -imgH / 2, imgW, imgH);
    ctx.restore();
    return;
  }
  _drawShipChevron(ctx, cx, cy, headingRad, halfSize, colour);
}

function _drawShipChevron(ctx, cx, cy, headingRad, halfSize, colour) {
  const s = halfSize;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(headingRad);
  ctx.strokeStyle = colour;
  ctx.lineWidth   = 1.5;
  ctx.beginPath();
  ctx.moveTo(0, -s);
  ctx.lineTo(s * 0.7, s * 0.7);
  ctx.lineTo(0, s * 0.25);
  ctx.lineTo(-s * 0.7, s * 0.7);
  ctx.closePath();
  ctx.stroke();
  ctx.restore();
}
