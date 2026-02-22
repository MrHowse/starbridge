/**
 * Starbridge — SectorMap
 *
 * Manages three zoom levels for map-capable stations:
 *   'tactical'  — current world view (~30k units, handled by MapRenderer)
 *   'sector'    — full sector view (~75k units, handled by MapRenderer at wider range)
 *   'strategic' — multi-sector grid view (handled by SectorMap.renderStrategic)
 *
 * Usage (Captain example):
 *   const sm = new SectorMap({ allowedLevels: ['tactical','sector','strategic'],
 *                               defaultZoom: 'sector', onRoutePlot: (x, y) => ... });
 *   sm.updateSectorGrid(payload);    // from map.sector_grid WebSocket message
 *   sm.setMapRenderer(mapRenderer);  // link to existing MapRenderer
 *
 *   // In rAF loop:
 *   if (sm.isStrategic()) {
 *     sm.renderStrategic(strategicCanvas, now);
 *   } else {
 *     mapRenderer.render(now);  // tactical / sector handled by MapRenderer range
 *   }
 *
 *   // On keydown:
 *   sm.handleKey(e.key);
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SM_BG            = '#0a0a0a';
const SM_GRID          = 'rgba(0, 255, 65, 0.15)';
const SM_GRID_BRIGHT   = 'rgba(0, 255, 65, 0.4)';
const SM_TEXT          = '#00ff41';
const SM_TEXT_DIM      = 'rgba(0, 255, 65, 0.45)';
const SM_UNKNOWN_FILL  = '#050505';
const SM_UNKNOWN_SCAN  = 'rgba(0, 20, 0, 0.7)';  // scanline pattern overlay
const SM_SHIP_COLOR    = '#00ff41';
const SM_ROUTE_COLOR   = '#ffb000';

// Visibility colours (fill tint for sector cells)
const SM_VIS_FILL = {
  unknown:     '#050505',
  transponder: 'rgba(0, 30, 0, 0.95)',
  scanned:     'rgba(0, 40, 10, 0.90)',
  surveyed:    'rgba(0, 60, 20, 0.85)',
  active:      'rgba(0, 80, 20, 0.80)',
  visited:     'rgba(0, 50, 10, 0.88)',
};

// Feature icon characters
const SM_FEATURE_ICONS = {
  friendly_station: '⬡',
  enemy_station:    '▲',
  derelict:         '◇',
  asteroid_field:   '◊',
  transponder:      '◉',
};

// Sector type border tints (left-edge accent)
const SM_TYPE_ACCENT = {
  hostile_space:    'rgba(255, 64, 64, 0.6)',
  contested_space:  'rgba(255, 176, 0, 0.5)',
  nebula:           'rgba(140, 80, 255, 0.5)',
  asteroid_field:   'rgba(180, 140, 80, 0.5)',
  radiation_zone:   'rgba(180, 255, 60, 0.5)',
  gravity_well:     'rgba(60, 180, 255, 0.5)',
  friendly_space:   'rgba(0, 170, 255, 0.4)',
  deep_space:       null,
};

// MapRenderer ranges for each zoom level.
export const ZOOM_RANGES = {
  tactical: 100_000,
  sector:   75_000,
  strategic: null,   // strategic uses its own renderer
};

// ---------------------------------------------------------------------------
// SectorMap
// ---------------------------------------------------------------------------

export class SectorMap {
  /**
   * @param {object} opts
   * @param {string[]} opts.allowedLevels  - Subset of ['tactical','sector','strategic']
   * @param {string}   opts.defaultZoom   - Starting zoom level
   * @param {function} opts.onRoutePlot   - Called with (worldX, worldY) on strategic-map click
   * @param {function} opts.onZoomChange  - Called with (newLevel) when zoom changes
   */
  constructor(opts = {}) {
    this._allowed  = opts.allowedLevels ?? ['tactical'];
    this._zoom     = opts.defaultZoom   ?? this._allowed[0];
    this._onRoute  = opts.onRoutePlot   ?? null;
    this._onZoom   = opts.onZoomChange  ?? null;

    // Ensure defaultZoom is actually allowed.
    if (!this._allowed.includes(this._zoom)) this._zoom = this._allowed[0];

    // Data from server.
    this._gridData        = null;    // map.sector_grid payload
    this._stationEntities = [];      // station_entities from map.sector_grid
    this._shipX    = 50_000;
    this._shipY    = 50_000;
    this._shipHead = 0;

    // MapRenderer reference — updated when zoom changes tactical/sector range.
    this._mapRenderer = null;
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  /** Link the MapRenderer so SectorMap can adjust its range on zoom change. */
  setMapRenderer(mr) {
    this._mapRenderer = mr;
    this._applyRangeToRenderer();
  }

  /** Handle a map.sector_grid WebSocket payload. */
  updateSectorGrid(payload) {
    this._gridData        = payload;
    this._stationEntities = payload.station_entities || [];
    // Re-apply sector range in case we were waiting for grid data.
    if (this._zoom === 'sector') this._applyRangeToRenderer();
  }

  /** Update the ship world position (for strategic ship marker). */
  updateShipPosition(x, y, heading = 0) {
    this._shipX    = x;
    this._shipY    = y;
    this._shipHead = heading;
  }

  /** Return the current zoom level string. */
  getZoomLevel() { return this._zoom; }

  /** Return true when in strategic mode (caller should use renderStrategic). */
  isStrategic() { return this._zoom === 'strategic'; }

  /** Set zoom level directly (must be in allowedLevels). */
  setZoomLevel(level) {
    if (!this._allowed.includes(level)) return;
    const prev = this._zoom;
    this._zoom = level;
    if (level !== prev) {
      this._applyRangeToRenderer();
      if (this._onZoom) this._onZoom(level);
    }
  }

  /** Cycle to the next allowed zoom level. */
  cycleZoom() {
    const idx = this._allowed.indexOf(this._zoom);
    this.setZoomLevel(this._allowed[(idx + 1) % this._allowed.length]);
    return this._zoom;
  }

  /**
   * Handle keyboard shortcut.
   *   Z           → cycle zoom
   *   1/2/3       → tactical / sector / strategic (if allowed)
   * Returns true if the key was consumed.
   */
  handleKey(key) {
    const k = key.toLowerCase();
    if (k === 'z') { this.cycleZoom(); return true; }
    if (k === '1' && this._allowed[0]) { this.setZoomLevel(this._allowed[0]); return true; }
    if (k === '2' && this._allowed[1]) { this.setZoomLevel(this._allowed[1]); return true; }
    if (k === '3' && this._allowed[2]) { this.setZoomLevel(this._allowed[2]); return true; }
    return false;
  }

  /**
   * Human-readable label for the current zoom level (for display in header).
   */
  zoomLabel() {
    switch (this._zoom) {
      case 'tactical':  return 'TACTICAL';
      case 'sector':    return 'SECTOR';
      case 'strategic': return 'STRATEGIC';
      default: return this._zoom.toUpperCase();
    }
  }

  /**
   * Render the strategic grid on *canvas*.
   * Call this instead of mapRenderer.render() when isStrategic() is true.
   */
  renderStrategic(canvas, now = performance.now()) {
    if (!this._gridData) return;

    // Auto-resize.
    const rect = canvas.getBoundingClientRect();
    if (rect.width > 0 &&
        (canvas.width  !== Math.round(rect.width) ||
         canvas.height !== Math.round(rect.height))) {
      canvas.width  = Math.round(rect.width);
      canvas.height = Math.round(rect.height);
    }

    const ctx = canvas.getContext('2d');
    const W   = canvas.width;
    const H   = canvas.height;

    ctx.fillStyle = SM_BG;
    ctx.fillRect(0, 0, W, H);

    const [cols, rows] = this._gridData.grid_size;
    const PAD     = 8;
    const cellW   = (W - PAD * 2) / cols;
    const cellH   = (H - PAD * 2) / rows;
    const sectors = this._gridData.sectors;

    // Draw each sector cell.
    for (const [sid, s] of Object.entries(sectors)) {
      const [col, row] = s.grid_position;
      const x = PAD + col * cellW;
      const y = PAD + row * cellH;
      this._drawCell(ctx, x, y, cellW, cellH, s, now);
    }

    // Route overlay.
    this._drawRoute(ctx, W, H, PAD, cellW, cellH, cols, rows, now);

    // Ship marker.
    this._drawShipMarker(ctx, W, H, PAD, cellW, cellH, cols, rows, now);

    // Grid labels (column letters top, row numbers left).
    this._drawGridLabels(ctx, W, H, PAD, cellW, cellH, cols, rows);

    // Zoom label.
    ctx.fillStyle    = SM_TEXT_DIM;
    ctx.font         = '8px "Share Tech Mono", monospace';
    ctx.textAlign    = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillText('STRATEGIC', W - 4, H - 2);
  }

  /**
   * Set up a click handler on *canvas* for route plotting in strategic mode.
   * Converts canvas click → world coordinates → calls onRoutePlot(x, y).
   */
  setupStrategicClick(canvas) {
    canvas.addEventListener('click', (e) => {
      if (!this.isStrategic() || !this._gridData || !this._onRoute) return;
      const rect  = canvas.getBoundingClientRect();
      const mx    = (e.clientX - rect.left) * (canvas.width  / rect.width);
      const my    = (e.clientY - rect.top)  * (canvas.height / rect.height);
      const [cols, rows] = this._gridData.grid_size;
      const PAD   = 8;
      const cellW = (canvas.width  - PAD * 2) / cols;
      const cellH = (canvas.height - PAD * 2) / rows;
      const col   = (mx - PAD) / cellW;
      const row   = (my - PAD) / cellH;
      if (col < 0 || col >= cols || row < 0 || row >= rows) return;
      // Convert cell position to world coordinates (centre of clicked cell).
      const wx = (Math.floor(col) + 0.5) * (100_000 / (1 / cols) * cols / cols);
      const wy = (Math.floor(row) + 0.5) * (100_000 / (1 / rows) * rows / rows);
      // Simpler: each cell is 100k world units wide.
      const worldX = (Math.floor(col) + 0.5) * 100_000;
      const worldY = (Math.floor(row) + 0.5) * 100_000;
      this._onRoute(worldX, worldY);
    });
  }

  // ── Private rendering ──────────────────────────────────────────────────────

  _applyRangeToRenderer() {
    if (!this._mapRenderer) return;
    if (this._zoom === 'sector') {
      this._applySectorRange();
    } else {
      const range = ZOOM_RANGES[this._zoom];
      if (range != null) {
        this._mapRenderer._range = range;
        this._mapRenderer.clearCameraOverride();
      }
    }
  }

  /**
   * Compute the active sector's world bounds and configure the MapRenderer
   * to show the entire sector centred, with a 10% margin.
   * Falls back to the old fixed 75k range (ship-centred) if no sector data.
   */
  _applySectorRange() {
    if (!this._gridData) {
      this._mapRenderer._range = ZOOM_RANGES.sector;
      this._mapRenderer.clearCameraOverride();
      return;
    }
    // Find the sector the ship is currently in.
    const sectors = this._gridData.sectors;
    let activeSector = null;
    for (const s of Object.values(sectors)) {
      if (s.visibility === 'active') { activeSector = s; break; }
    }
    if (!activeSector) {
      this._mapRenderer._range = ZOOM_RANGES.sector;
      this._mapRenderer.clearCameraOverride();
      return;
    }
    // Each sector is 100,000 × 100,000 world units.
    const [col, row] = activeSector.grid_position;
    const SECTOR_SIZE = 100_000;
    const cxWorld = (col + 0.5) * SECTOR_SIZE;
    const cyWorld = (row + 0.5) * SECTOR_SIZE;
    const range   = SECTOR_SIZE / 2 * 1.1;   // 55,000 — sector radius + 10% margin
    this._mapRenderer._range = range;
    this._mapRenderer.setCameraOverride(cxWorld, cyWorld);
  }

  _drawCell(ctx, x, y, w, h, sector, now) {
    const vis  = sector.visibility || 'unknown';
    const fill = SM_VIS_FILL[vis] || SM_VIS_FILL.unknown;

    // Cell background.
    ctx.fillStyle = fill;
    ctx.fillRect(x, y, w, h);

    // Scanline pattern for unknown sectors.
    if (vis === 'unknown') {
      ctx.save();
      ctx.strokeStyle = 'rgba(0, 255, 65, 0.03)';
      ctx.lineWidth   = 1;
      for (let ly = y + 2; ly < y + h; ly += 4) {
        ctx.beginPath();
        ctx.moveTo(x, ly);
        ctx.lineTo(x + w, ly);
        ctx.stroke();
      }
      ctx.restore();
    }

    // Sector type left-edge accent.
    const accent = SM_TYPE_ACCENT[sector.properties?.type];
    if (accent) {
      ctx.fillStyle = accent;
      ctx.fillRect(x, y, 3, h);
    }

    // Cell border.
    ctx.strokeStyle = SM_GRID;
    ctx.lineWidth   = 0.5;
    ctx.strokeRect(x, y, w, h);

    // Highlight current sector (active).
    if (vis === 'active') {
      ctx.strokeStyle = SM_GRID_BRIGHT;
      ctx.lineWidth   = 1.5;
      ctx.strokeRect(x + 1, y + 1, w - 2, h - 2);
    }

    // Sector ID label.
    ctx.fillStyle    = vis === 'unknown' ? 'rgba(0, 255, 65, 0.15)' : SM_TEXT;
    ctx.font         = `${Math.min(10, w * 0.18)}px "Share Tech Mono", monospace`;
    ctx.textAlign    = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(sector.id, x + 4, y + 3);

    if (vis === 'unknown') return;  // don't show name/features for unknown sectors

    // Sector name (smaller, wraps if needed).
    const nameFont = Math.min(7, w * 0.13);
    ctx.fillStyle    = SM_TEXT_DIM;
    ctx.font         = `${nameFont}px "Share Tech Mono", monospace`;
    ctx.textAlign    = 'left';
    ctx.textBaseline = 'top';
    const name = sector.name || '';
    ctx.fillText(name.slice(0, 14), x + 4, y + 14);

    // Feature icons (bottom of cell).
    const features = sector.features || [];
    let iconX = x + 4;
    const iconY = y + h - 14;
    ctx.font         = `${Math.min(11, h * 0.18)}px monospace`;
    ctx.textBaseline = 'middle';
    for (const f of features) {
      if (!f.visible_without_scan && vis === 'transponder') continue;
      const icon = SM_FEATURE_ICONS[f.type];
      if (!icon) continue;
      ctx.fillStyle = f.type === 'enemy_station'
        ? 'rgba(255,64,64,0.7)'
        : 'rgba(0, 170, 255, 0.7)';
      ctx.fillText(icon, iconX, iconY);
      iconX += 12;
      if (iconX > x + w - 8) break;
    }

    // Threat level dot (top-right corner).
    const threat = sector.properties?.threat_level;
    if (threat && threat !== 'low') {
      const dotColor = threat === 'high' ? 'rgba(255,64,64,0.8)' : 'rgba(255,176,0,0.8)';
      ctx.fillStyle = dotColor;
      ctx.beginPath();
      ctx.arc(x + w - 6, y + 6, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  _drawRoute(ctx, W, H, PAD, cellW, cellH, cols, rows, now) {
    const route = this._gridData?.route;
    if (!route || !route.plot_x) return;

    const fromSx = PAD + (route.from_x / (cols * 100_000)) * (W - PAD * 2);
    const fromSy = PAD + (route.from_y / (rows * 100_000)) * (H - PAD * 2);
    const toSx   = PAD + (route.plot_x / (cols * 100_000)) * (W - PAD * 2);
    const toSy   = PAD + (route.plot_y / (rows * 100_000)) * (H - PAD * 2);

    // Dashed amber route line.
    const pulse = 0.6 + 0.4 * Math.sin(now * 0.003);
    ctx.save();
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = `rgba(255, 176, 0, ${pulse})`;
    ctx.lineWidth   = 1.5;
    ctx.beginPath();
    ctx.moveTo(fromSx, fromSy);
    ctx.lineTo(toSx, toSy);
    ctx.stroke();
    ctx.setLineDash([]);

    // Destination marker.
    ctx.fillStyle = `rgba(255, 176, 0, ${pulse})`;
    ctx.beginPath();
    ctx.arc(toSx, toSy, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  _drawShipMarker(ctx, W, H, PAD, cellW, cellH, cols, rows, now) {
    const sx = PAD + (this._shipX / (cols * 100_000)) * (W - PAD * 2);
    const sy = PAD + (this._shipY / (rows * 100_000)) * (H - PAD * 2);
    const pulse = 0.7 + 0.3 * Math.sin(now * 0.004);

    ctx.save();
    ctx.fillStyle = `rgba(0, 255, 65, ${pulse})`;
    ctx.beginPath();
    ctx.arc(sx, sy, 4, 0, Math.PI * 2);
    ctx.fill();

    // Chevron pointing in ship heading direction.
    const headRad = this._shipHead * Math.PI / 180;
    ctx.strokeStyle = SM_SHIP_COLOR;
    ctx.lineWidth   = 1.5;
    const s = 6;
    ctx.translate(sx, sy);
    ctx.rotate(headRad);
    ctx.beginPath();
    ctx.moveTo(0, -s);
    ctx.lineTo(s * 0.6,  s * 0.6);
    ctx.lineTo(0, s * 0.2);
    ctx.lineTo(-s * 0.6, s * 0.6);
    ctx.closePath();
    ctx.stroke();
    ctx.restore();
  }

  _drawGridLabels(ctx, W, H, PAD, cellW, cellH, cols, rows) {
    ctx.fillStyle    = SM_TEXT_DIM;
    ctx.font         = '7px "Share Tech Mono", monospace';
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'top';
    // Column letters (top).
    for (let c = 0; c < cols; c++) {
      const letter = String.fromCharCode(65 + c);
      ctx.fillText(letter, PAD + (c + 0.5) * cellW, 1);
    }
    // Row numbers (left).
    ctx.textAlign    = 'right';
    ctx.textBaseline = 'middle';
    for (let r = 0; r < rows; r++) {
      ctx.fillText(String(r + 1), PAD - 1, PAD + (r + 0.5) * cellH);
    }
  }

  /**
   * Draw sector boundary lines and adjacent sector name labels on the map
   * canvas when in sector mode. Must be called after mapRenderer.render().
   *
   * @param {CanvasRenderingContext2D} ctx
   * @param {HTMLCanvasElement}        canvas
   * @param {MapRenderer}              mapRenderer
   */
  renderSectorBoundaryOverlay(ctx, canvas, mapRenderer) {
    if (this._zoom !== 'sector' || !this._gridData || !mapRenderer) return;

    // Find the active sector.
    const sectors = this._gridData.sectors;
    let activeSector = null;
    for (const s of Object.values(sectors)) {
      if (s.visibility === 'active') { activeSector = s; break; }
    }
    if (!activeSector) return;

    const [col, row] = activeSector.grid_position;
    const SECTOR_SIZE = 100_000;
    const minX = col * SECTOR_SIZE;
    const minY = row * SECTOR_SIZE;
    const maxX = (col + 1) * SECTOR_SIZE;
    const maxY = (row + 1) * SECTOR_SIZE;

    const cw = canvas.width;
    const ch = canvas.height;

    // Sector corners in canvas coordinates.
    const tl = mapRenderer.worldToCanvas(minX, minY);
    const tr = mapRenderer.worldToCanvas(maxX, minY);
    const br = mapRenderer.worldToCanvas(maxX, maxY);
    const bl = mapRenderer.worldToCanvas(minX, maxY);

    ctx.save();

    // Dashed sector boundary rectangle.
    ctx.strokeStyle = 'rgba(0, 255, 65, 0.35)';
    ctx.lineWidth   = 1;
    ctx.setLineDash([6, 5]);
    ctx.beginPath();
    ctx.moveTo(tl.x, tl.y);
    ctx.lineTo(tr.x, tr.y);
    ctx.lineTo(br.x, br.y);
    ctx.lineTo(bl.x, bl.y);
    ctx.closePath();
    ctx.stroke();
    ctx.setLineDash([]);

    // Active sector label (top-left corner of sector boundary).
    ctx.fillStyle    = 'rgba(0, 255, 65, 0.55)';
    ctx.font         = '9px "Share Tech Mono", monospace';
    ctx.textAlign    = 'left';
    ctx.textBaseline = 'top';
    const sectorLabel = activeSector.name
      ? `${activeSector.id} — ${activeSector.name}`
      : activeSector.id;
    ctx.fillText(sectorLabel.slice(0, 24), tl.x + 4, tl.y + 4);

    // Adjacent sector labels at each edge midpoint.
    const [cols, rows] = this._gridData.grid_size;
    const neighbors = [
      { dc: 0, dr: -1, ex: (minX + maxX) / 2, ey: minY, align: 'center', base: 'bottom', dx: 0, dy: -4 },
      { dc: 0, dr:  1, ex: (minX + maxX) / 2, ey: maxY, align: 'center', base: 'top',    dx: 0, dy:  4 },
      { dc: -1, dr: 0, ex: minX, ey: (minY + maxY) / 2, align: 'right',  base: 'middle', dx: -4, dy: 0 },
      { dc:  1, dr: 0, ex: maxX, ey: (minY + maxY) / 2, align: 'left',   base: 'middle', dx:  4, dy: 0 },
    ];

    for (const n of neighbors) {
      const nc = col + n.dc;
      const nr = row + n.dr;
      if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) continue;
      const neighbor = Object.values(sectors).find(
        s => s.grid_position[0] === nc && s.grid_position[1] === nr,
      );
      if (!neighbor || neighbor.visibility === 'unknown') continue;

      const ep = mapRenderer.worldToCanvas(n.ex, n.ey);
      ctx.fillStyle    = 'rgba(0, 255, 65, 0.35)';
      ctx.font         = '8px "Share Tech Mono", monospace';
      ctx.textAlign    = n.align;
      ctx.textBaseline = n.base;
      const tag = neighbor.name ? `${neighbor.id}: ${neighbor.name}` : neighbor.id;
      ctx.fillText(tag.slice(0, 18), ep.x + n.dx, ep.y + n.dy);
    }

    // Sector zoom label (bottom-right corner of canvas).
    ctx.fillStyle    = 'rgba(0, 255, 65, 0.45)';
    ctx.font         = '8px "Share Tech Mono", monospace';
    ctx.textAlign    = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillText('SECTOR', cw - 4, ch - 4);

    ctx.restore();
  }

  /**
   * Overlay station icons on a tactical/sector MapRenderer canvas (v0.05e).
   * Must be called after mapRenderer.render() so icons appear on top.
   *
   * @param {CanvasRenderingContext2D} ctx  - Canvas 2D context of the map canvas
   * @param {HTMLCanvasElement}        canvas
   * @param {MapRenderer}              mapRenderer - For worldToCanvas() transform
   */
  renderStationOverlay(ctx, canvas, mapRenderer) {
    if (!this._stationEntities.length || !mapRenderer || this._zoom === 'strategic') return;
    ctx.save();
    for (const st of this._stationEntities) {
      if (!st.transponder_active) continue;
      const { x: sx, y: sy } = mapRenderer.worldToCanvas(st.x, st.y);
      // Skip stations well outside the visible canvas area.
      if (sx < -30 || sy < -30 || sx > canvas.width + 30 || sy > canvas.height + 30) continue;
      this._drawStationIcon(ctx, sx, sy, st);
    }
    ctx.restore();
  }

  /** Draw a single station icon on the map canvas at screen coords (sx, sy). */
  _drawStationIcon(ctx, sx, sy, station) {
    const color = station.faction === 'hostile' ? '#ff4040'
                : station.faction === 'neutral'  ? '#ffb000'
                :                                  '#00aaff';
    const r = 7;
    // Hexagon outline.
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1.5;
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = (i * Math.PI) / 3 - Math.PI / 6;
      if (i === 0) ctx.moveTo(sx + Math.cos(a) * r, sy + Math.sin(a) * r);
      else         ctx.lineTo(sx + Math.cos(a) * r, sy + Math.sin(a) * r);
    }
    ctx.closePath();
    ctx.stroke();
    // Centre dot.
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(sx, sy, 2, 0, Math.PI * 2);
    ctx.fill();
    // Name label below icon.
    const label = station.name || station.id;
    ctx.fillStyle    = color + '99';
    ctx.font         = '8px "Share Tech Mono", monospace';
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(label.slice(0, 12), sx, sy + r + 2);
  }
}
