/**
 * Puzzle type: Route Calculation
 *
 * Helm station — plot a safe path through a hazard grid from (0,0) to
 * (size-1, size-1). Click cells to build a path; re-click the last cell
 * or an earlier cell to truncate. Hidden cells have unknown status until
 * a Science assist reveals them.
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

let _container = null;
let _canvas    = null;
let _ctx       = null;

let _gridSize  = 5;
let _cells     = [];      // 2D array of { type: 'safe'|'hazard'|'hidden' }
let _path      = [];      // [[row, col], ...] — player's built path
let _start     = [0, 0];
let _end       = [0, 0];

// Colours.
const C = {
  bg:        '#0a0e0a',
  grid:      '#1a2a1a',
  safe:      '#0d2b12',
  hazard:    '#2b0d0d',
  hidden:    '#1c1c1c',
  pathCell:  '#0d3320',
  startCell: '#0d1f2b',
  endCell:   '#2b2200',
  border:    '#2a3a2a',
  pathLine:  '#00ff41',
  startLine: '#00c8ff',
  endLine:   '#ffcc00',
  textDim:   '#556655',
  textBright:'#ccffcc',
  textHazard:'#ff4040',
  textHidden:'#888888',
  textStart: '#00c8ff',
  textEnd:   '#ffcc00',
  revealed:  '#1a2a2a',   // revealed hidden cell background
};

const CELL_PADDING = 3;

// ---------------------------------------------------------------------------
// Interface
// ---------------------------------------------------------------------------

/**
 * @param {HTMLElement} container
 * @param {Object} puzzleData — { grid_size, cells, start, end }
 */
export function init(container, puzzleData) {
  _container = container;
  _gridSize  = puzzleData.grid_size || 5;
  _start     = puzzleData.start || [0, 0];
  _end       = puzzleData.end   || [_gridSize - 1, _gridSize - 1];

  // Deep-copy cells so assists can mutate.
  _cells = puzzleData.cells.map(row => row.map(cell => ({ ...cell })));

  // Path starts at the start cell.
  _path = [[..._start]];

  _buildDOM();
  _render();
}

/**
 * Apply Science sensor assist: reveal a hidden cell.
 * @param {Object} assistData — { row, col, safe } or {}
 */
export function applyAssist(assistData) {
  const { row, col, safe } = assistData;
  if (row == null || col == null) return;

  _cells[row][col] = { type: safe ? 'safe' : 'hazard', revealed: true };

  // If revealed cell is hazard and it's in the player's path, truncate.
  if (!safe) {
    const idx = _path.findIndex(([r, c]) => r === row && c === col);
    if (idx !== -1) {
      _path = _path.slice(0, idx);
      if (_path.length === 0) _path = [[..._start]];
    }
  }

  _render();
  _flashCell(row, col);
}

/**
 * Return the player's current submission.
 * @returns {{ path: number[][] }}
 */
export function getSubmission() {
  return { path: _path.map(([r, c]) => [r, c]) };
}

/** Remove all DOM created by this module. */
export function destroy() {
  _canvas = null;
  _ctx = null;
  if (_container) _container.innerHTML = '';
  _container = null;
  _path = [];
  _cells = [];
}

// ---------------------------------------------------------------------------
// DOM construction
// ---------------------------------------------------------------------------

function _buildDOM() {
  _container.innerHTML = '';
  _container.className = 'rc-layout';

  // Instructions.
  const instr = document.createElement('p');
  instr.className = 'rc-instructions text-dim text-label';
  instr.textContent = 'Click cells to build a path from START to END. Click a cell again to truncate.';
  _container.appendChild(instr);

  // Canvas.
  _canvas = document.createElement('canvas');
  _canvas.className = 'rc-canvas';
  _container.appendChild(_canvas);

  // Legend.
  const legend = document.createElement('div');
  legend.className = 'rc-legend';
  legend.innerHTML = `
    <span class="rc-legend-item"><span class="rc-swatch rc-swatch--safe"></span>SAFE</span>
    <span class="rc-legend-item"><span class="rc-swatch rc-swatch--hazard"></span>HAZARD</span>
    <span class="rc-legend-item"><span class="rc-swatch rc-swatch--hidden"></span>UNKNOWN</span>
    <span class="rc-legend-item"><span class="rc-swatch rc-swatch--path"></span>PATH</span>
  `;
  _container.appendChild(legend);

  _canvas.addEventListener('click', _onCanvasClick);
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _render() {
  if (!_canvas) return;

  // Size canvas to fit the container.
  const maxSize = Math.min(_container.clientWidth || 280, 320);
  const cellSize = Math.floor((maxSize - CELL_PADDING * (_gridSize + 1)) / _gridSize);
  const canvasSize = cellSize * _gridSize + CELL_PADDING * (_gridSize + 1);

  _canvas.width  = canvasSize;
  _canvas.height = canvasSize;
  _ctx = _canvas.getContext('2d');

  const ctx = _ctx;
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, canvasSize, canvasSize);

  const pathSet = new Set(_path.map(([r, c]) => `${r},${c}`));

  for (let r = 0; r < _gridSize; r++) {
    for (let c = 0; c < _gridSize; c++) {
      const x = CELL_PADDING + c * (cellSize + CELL_PADDING);
      const y = CELL_PADDING + r * (cellSize + CELL_PADDING);
      _drawCell(ctx, r, c, x, y, cellSize, pathSet);
    }
  }

  // Draw path lines connecting cells in order.
  if (_path.length >= 2) {
    ctx.save();
    ctx.strokeStyle = C.pathLine;
    ctx.lineWidth   = 2.5;
    ctx.lineCap     = 'round';
    ctx.lineJoin    = 'round';
    ctx.globalAlpha = 0.7;
    ctx.beginPath();
    for (let i = 0; i < _path.length; i++) {
      const [pr, pc] = _path[i];
      const px = CELL_PADDING + pc * (cellSize + CELL_PADDING) + cellSize / 2;
      const py = CELL_PADDING + pr * (cellSize + CELL_PADDING) + cellSize / 2;
      if (i === 0) ctx.moveTo(px, py);
      else         ctx.lineTo(px, py);
    }
    ctx.stroke();
    ctx.restore();
  }
}

function _drawCell(ctx, r, c, x, y, size, pathSet) {
  const isStart  = r === _start[0] && c === _start[1];
  const isEnd    = r === _end[0]   && c === _end[1];
  const isOnPath = pathSet.has(`${r},${c}`);
  const isLast   = _path.length > 0 && _path[_path.length - 1][0] === r && _path[_path.length - 1][1] === c;

  const cell = _cells[r][c];
  const type = cell.type;

  // Background.
  let bg = C.grid;
  if (isStart)       bg = C.startCell;
  else if (isEnd)    bg = C.endCell;
  else if (isOnPath) bg = C.pathCell;
  else if (type === 'safe')   bg = C.safe;
  else if (type === 'hazard') bg = C.hazard;
  else if (type === 'hidden') bg = C.hidden;

  ctx.fillStyle = bg;
  _roundRect(ctx, x, y, size, size, 3);
  ctx.fill();

  // Border — highlight last path cell.
  ctx.strokeStyle = isLast ? C.pathLine : C.border;
  ctx.lineWidth   = isLast ? 1.5 : 0.5;
  _roundRect(ctx, x, y, size, size, 3);
  ctx.stroke();

  // Cell label.
  const fontSize = Math.max(7, Math.floor(size * 0.28));
  ctx.font      = `${fontSize}px monospace`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const cx = x + size / 2;
  const cy = y + size / 2;

  if (isStart) {
    ctx.fillStyle = C.textStart;
    ctx.fillText('S', cx, cy);
  } else if (isEnd) {
    ctx.fillStyle = C.textEnd;
    ctx.fillText('E', cx, cy);
  } else if (type === 'hazard') {
    ctx.fillStyle = C.textHazard;
    ctx.fillText('✕', cx, cy);
  } else if (type === 'hidden') {
    ctx.fillStyle = C.textHidden;
    ctx.fillText('?', cx, cy);
  } else if (type === 'safe' && isOnPath) {
    // Show step number.
    const step = _path.findIndex(([pr, pc]) => pr === r && pc === c) + 1;
    ctx.fillStyle = C.textBright;
    ctx.fillText(String(step), cx, cy);
  }
}

function _roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.arcTo(x + w, y, x + w, y + r, r);
  ctx.lineTo(x + w, y + h - r);
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.lineTo(x + r, y + h);
  ctx.arcTo(x, y + h, x, y + h - r, r);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();
}

// ---------------------------------------------------------------------------
// Interaction
// ---------------------------------------------------------------------------

function _onCanvasClick(e) {
  if (!_canvas) return;
  const rect     = _canvas.getBoundingClientRect();
  const scaleX   = _canvas.width  / rect.width;
  const scaleY   = _canvas.height / rect.height;
  const mouseX   = (e.clientX - rect.left) * scaleX;
  const mouseY   = (e.clientY - rect.top)  * scaleY;

  const canvasSize = _canvas.width;
  const cellSize   = Math.floor((canvasSize - CELL_PADDING * (_gridSize + 1)) / _gridSize);

  const col = Math.floor((mouseX - CELL_PADDING) / (cellSize + CELL_PADDING));
  const row = Math.floor((mouseY - CELL_PADDING) / (cellSize + CELL_PADDING));

  if (col < 0 || col >= _gridSize || row < 0 || row >= _gridSize) return;

  _onCellClick(row, col);
}

function _onCellClick(row, col) {
  // Can't click hazard cells directly.
  if (_cells[row][col].type === 'hazard') return;

  const existing = _path.findIndex(([r, c]) => r === row && c === col);

  if (existing !== -1) {
    // Truncate path to this cell (inclusive) — unless it's the start.
    if (existing === 0) return;  // can't remove start
    _path = _path.slice(0, existing + 1);
    _render();
    return;
  }

  // Check adjacency to last cell in path.
  if (_path.length === 0) return;
  const [lr, lc] = _path[_path.length - 1];
  const dr = Math.abs(row - lr);
  const dc = Math.abs(col - lc);
  if (dr + dc !== 1) return;  // not adjacent

  _path.push([row, col]);
  _render();
}

// ---------------------------------------------------------------------------
// Assist flash
// ---------------------------------------------------------------------------

let _flashTimeout = null;

function _flashCell(row, col) {
  // Store flash target for one frame highlight.
  if (_flashTimeout) clearTimeout(_flashTimeout);
  if (!_canvas || !_ctx) return;

  const canvasSize = _canvas.width;
  const cellSize   = Math.floor((canvasSize - CELL_PADDING * (_gridSize + 1)) / _gridSize);
  const x = CELL_PADDING + col * (cellSize + CELL_PADDING);
  const y = CELL_PADDING + row * (cellSize + CELL_PADDING);

  // Draw a brief highlight ring.
  _ctx.save();
  _ctx.strokeStyle = '#00ffff';
  _ctx.lineWidth   = 2;
  _ctx.shadowColor  = '#00ffff';
  _ctx.shadowBlur   = 8;
  _roundRect(_ctx, x - 1, y - 1, cellSize + 2, cellSize + 2, 4);
  _ctx.stroke();
  _ctx.restore();

  _flashTimeout = setTimeout(() => _render(), 800);
}
