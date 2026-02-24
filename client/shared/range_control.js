/**
 * Starbridge — RangeControl
 *
 * Shared range selector for map-capable stations.  Renders a row of
 * range buttons and manages keyboard shortcuts ([ / ] to step).
 *
 * Usage:
 *   const rc = new RangeControl({
 *     container:  document.getElementById('range-bar'),
 *     ranges:     ['25', '50', '100', '500', '1K', '5K', 'SEC', 'STR'],
 *     defaultRange: '100',
 *     onChange:   (rangeKey) => { ... },
 *   });
 *   rc.attach();                        // renders buttons + wires keys
 *   rc.setRange('50');                   // programmatic switch
 *   rc.currentRange();                   // → '50'
 *   rc.currentRangeUnits();              // → 50_000  (world units)
 *   rc.setSectorBounds(cx, cy, size);    // data for SEC auto-calc
 *   rc.setStrategicGrid(gridData);       // data for STR auto-calc
 */

// ---------------------------------------------------------------------------
// Range definitions
// ---------------------------------------------------------------------------

/** All possible range presets.  key → { label, worldUnits, km }. */
export const RANGE_PRESETS = {
  '25':  { label: '25',  worldUnits:     25_000, km:    25 },
  '50':  { label: '50',  worldUnits:     50_000, km:    50 },
  '100': { label: '100', worldUnits:    100_000, km:   100 },
  '500': { label: '500', worldUnits:    500_000, km:   500 },
  '1K':  { label: '1K',  worldUnits:  1_000_000, km:  1000 },
  '5K':  { label: '5K',  worldUnits:  5_000_000, km:  5000 },
  'SEC': { label: 'SEC', worldUnits:     55_000, km:    55 },   // default; overridden by setSectorBounds
  'STR': { label: 'STR', worldUnits:          0, km:     0 },   // strategic; handled specially
};

/** Per-station presets. */
export const STATION_RANGES = {
  captain:  { available: ['25','50','100','500','1K','5K','SEC','STR'], default: '100' },
  helm:     { available: ['25','50','100','500','1K','SEC'],           default: '50'  },
  weapons:  { available: ['25','50','100'],                            default: '50'  },
  science:  { available: ['25','50','100','500','1K','SEC','STR'],     default: '100' },
  tactical: { available: ['25','50','100','500','1K','SEC','STR'],     default: '100' },
  flight_ops: { available: ['25','50','100','500'],                    default: '50'  },
  electronic_warfare: { available: ['25','50','100'],                  default: '50'  },
};

// ---------------------------------------------------------------------------
// RangeControl
// ---------------------------------------------------------------------------

export class RangeControl {
  /**
   * @param {object} opts
   * @param {HTMLElement}  opts.container    - DOM element to render buttons into
   * @param {string[]}     opts.ranges       - Ordered list of range keys to show
   * @param {string}       opts.defaultRange - Initial range key
   * @param {function}     opts.onChange      - Called with (rangeKey, worldUnits) on change
   */
  constructor(opts = {}) {
    this._container  = opts.container;
    this._ranges     = opts.ranges ?? ['50', '100'];
    this._default    = opts.defaultRange ?? this._ranges[0];
    this._onChange    = opts.onChange ?? (() => {});
    this._stationId  = opts.stationId ?? null;
    this._current    = this._restoreRange() ?? this._default;
    this._buttons    = [];

    // Sector bounds for SEC auto-calc.
    this._sectorCX   = 50_000;
    this._sectorCY   = 50_000;
    this._sectorSize = 100_000;

    // Strategic grid data for STR.
    this._gridData = null;

    // Keyboard handler reference (for cleanup).
    this._keyHandler = null;
  }

  // ── Public API ────────────────────────────────────────────────────────

  /** Render the range buttons into the container and wire keyboard shortcuts. */
  attach() {
    this._renderButtons();
    this._keyHandler = (e) => this._handleKey(e);
    document.addEventListener('keydown', this._keyHandler);
    // Fire onChange with the restored range so the station initialises correctly.
    this._onChange(this._current, this.currentRangeUnits());
  }

  /** Remove keyboard listener. */
  detach() {
    if (this._keyHandler) {
      document.removeEventListener('keydown', this._keyHandler);
      this._keyHandler = null;
    }
  }

  /** Get the current range key (e.g. '50', 'SEC'). */
  currentRange() { return this._current; }

  /** Get the current range in world units. */
  currentRangeUnits() {
    if (this._current === 'SEC') return this._sectorRangeUnits();
    if (this._current === 'STR') return this._strategicRangeUnits();
    return RANGE_PRESETS[this._current]?.worldUnits ?? 50_000;
  }

  /** Is the current range the strategic multi-sector grid? */
  isStrategic() { return this._current === 'STR'; }

  /** Is the current range the sector fit view? */
  isSector() { return this._current === 'SEC'; }

  /** Programmatic range switch. */
  setRange(key) {
    if (!this._ranges.includes(key)) return;
    this._current = key;
    this._saveRange(key);
    this._updateUI();
    this._onChange(key, this.currentRangeUnits());
  }

  /** Provide sector bounds for SEC auto-calc. */
  setSectorBounds(cx, cy, size) {
    this._sectorCX   = cx;
    this._sectorCY   = cy;
    this._sectorSize = size;
  }

  /** Provide strategic grid data for STR. */
  setStrategicGrid(gridData) {
    this._gridData = gridData;
  }

  /** Get sector centre for camera override when in SEC mode. */
  getSectorCentre() {
    return { x: this._sectorCX, y: this._sectorCY };
  }

  /** Step to next range (direction: 1 = up, -1 = down). */
  step(direction) {
    const idx = this._ranges.indexOf(this._current);
    const next = idx + direction;
    if (next >= 0 && next < this._ranges.length) {
      this.setRange(this._ranges[next]);
    }
  }

  // ── Private ───────────────────────────────────────────────────────────

  _sectorRangeUnits() {
    // Fit the sector with 10% margin.
    return (this._sectorSize / 2) * 1.1;
  }

  _strategicRangeUnits() {
    if (!this._gridData) return 500_000;
    const [cols, rows] = this._gridData.grid_size || [5, 5];
    const SECTOR_SIZE = 100_000;
    return Math.max(cols, rows) * SECTOR_SIZE / 2 * 1.1;
  }

  _renderButtons() {
    if (!this._container) return;
    this._container.innerHTML = '';

    const label = document.createElement('span');
    label.className = 'range-label';
    label.textContent = 'RANGE:';
    this._container.appendChild(label);

    this._buttons = [];
    for (const key of this._ranges) {
      const preset = RANGE_PRESETS[key];
      if (!preset) continue;
      const btn = document.createElement('button');
      btn.className = 'range-btn';
      btn.dataset.range = key;
      btn.textContent = preset.label;
      btn.title = key === 'SEC' ? 'Fit sector to viewport'
                : key === 'STR' ? 'Strategic multi-sector grid'
                : `${preset.km}km range`;
      if (key === this._current) btn.classList.add('range-btn--active');
      btn.addEventListener('click', () => this.setRange(key));
      this._container.appendChild(btn);
      this._buttons.push(btn);
    }
  }

  _updateUI() {
    for (const btn of this._buttons) {
      btn.classList.toggle('range-btn--active', btn.dataset.range === this._current);
    }
  }

  _handleKey(e) {
    if (e.key === '[') { this.step(-1); e.preventDefault(); }
    if (e.key === ']') { this.step(1);  e.preventDefault(); }
  }

  _saveRange(key) {
    if (!this._stationId) return;
    try { sessionStorage.setItem(`starbridge_range_${this._stationId}`, key); } catch (_) { /* ignore */ }
  }

  _restoreRange() {
    if (!this._stationId) return null;
    try {
      const saved = sessionStorage.getItem(`starbridge_range_${this._stationId}`);
      return saved && this._ranges.includes(saved) ? saved : null;
    } catch (_) { return null; }
  }
}
