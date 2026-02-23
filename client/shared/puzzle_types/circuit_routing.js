/**
 * Puzzle type: Circuit Routing (Engineering)
 *
 * Canvas interaction: drag from one node to an adjacent node to place or
 * remove a conduit connection.  Spare conduits are limited.  When a valid
 * path exists from source to target, an animated flow effect confirms it.
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

// Grid geometry
let _gridRows = 0, _gridCols = 0;
let _nodes    = {};   // id → {id, row, col, type, x, y}
let _sourceId = '', _targetId = '';

// Edge sets (string: "r,c~r,c" canonical form)
let _existingEdges  = new Set();
let _availableEdges = new Set();
let _placedEdges    = new Set();
let _spareConduits  = 0;

// Assist state
let _highlightedNodes = new Set();

// Interaction
let _dragStart = null;   // node id being dragged from
let _mousePos  = { x: 0, y: 0 };

// Render loop
let _validPath   = null;  // array of node IDs if path exists, else null
let _flowOffset  = 0;
let _rAF         = null;

// DOM refs
let _statusEl = null;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * @param {HTMLElement} container
 * @param {Object} puzzleData
 */
export function init(container, puzzleData) {
  _container = container;

  const {
    grid_rows, grid_cols, nodes,
    existing_connections, available_connections,
    spare_conduits, source_id, target_id,
  } = puzzleData;

  _gridRows = grid_rows;
  _gridCols = grid_cols;
  _spareConduits = spare_conduits;
  _sourceId = source_id;
  _targetId = target_id;
  _placedEdges.clear();
  _highlightedNodes.clear();

  // Build node map.
  _nodes = {};
  for (const n of nodes) {
    _nodes[n.id] = { ...n, x: 0, y: 0 };
  }

  // Build edge sets.
  _existingEdges  = new Set(existing_connections.map(([a, b]) => _edgeId(a, b)));
  _availableEdges = new Set(available_connections.map(([a, b]) => _edgeId(a, b)));

  // Create canvas.
  _canvas = document.createElement('canvas');
  _canvas.className = 'circuit-canvas';
  _canvas.height = Math.max(180, grid_rows * 56);
  container.appendChild(_canvas);
  _ctx = _canvas.getContext('2d');

  // Status line beneath canvas.
  _statusEl = document.createElement('div');
  _statusEl.className = 'circuit-status';
  container.appendChild(_statusEl);

  // Wire mouse events.
  _canvas.addEventListener('mousedown',  _onMouseDown);
  _canvas.addEventListener('mousemove',  _onMouseMove);
  _canvas.addEventListener('mouseup',    _onMouseUp);
  _canvas.addEventListener('mouseleave', _onMouseLeave);

  // Recompute positions once the element is in the DOM (one frame delay).
  requestAnimationFrame(() => {
    _canvas.width = _canvas.offsetWidth || 300;
    _computeNodePositions();
    _validPath = _findPath(_sourceId, _targetId);
    _rAF = requestAnimationFrame(_draw);
  });
}

/** Apply an assist payload — highlights nodes on the solution path. */
export function applyAssist(assistData) {
  if (assistData.highlighted_nodes) {
    _highlightedNodes = new Set(assistData.highlighted_nodes);
  }
}

/** Return the player's current placed-conduit submission. */
export function getSubmission() {
  const placed = [..._placedEdges].map(eid => {
    const [a, b] = _edgeToNodeIds(eid);
    return [a, b];
  });
  return { placed_connections: placed };
}

/** Clean up the render loop and DOM. */
export function destroy() {
  if (_rAF !== null) cancelAnimationFrame(_rAF);
  _rAF = null;
  if (_container) _container.innerHTML = '';
  _canvas = null;
  _ctx = null;
  _container = null;
  _nodes = {};
  _existingEdges.clear();
  _availableEdges.clear();
  _placedEdges.clear();
  _highlightedNodes.clear();
}

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

function _parseNodeId(id) {
  // "r2c3" → [2, 3]
  const rest = id.slice(1);            // "2c3"
  const [rowStr, colStr] = rest.split('c');
  return [parseInt(rowStr, 10), parseInt(colStr, 10)];
}

function _edgeId(id1, id2) {
  const [r1, c1] = _parseNodeId(id1);
  const [r2, c2] = _parseNodeId(id2);
  if (r1 < r2 || (r1 === r2 && c1 < c2)) {
    return `${r1},${c1}~${r2},${c2}`;
  }
  return `${r2},${c2}~${r1},${c1}`;
}

function _edgeToNodeIds(eid) {
  // "2,1~3,1" → ["r2c1", "r3c1"]
  const [part1, part2] = eid.split('~');
  const [r1, c1] = part1.split(',').map(Number);
  const [r2, c2] = part2.split(',').map(Number);
  return [`r${r1}c${c1}`, `r${r2}c${c2}`];
}

function _areAdjacentNodes(id1, id2) {
  const [r1, c1] = _parseNodeId(id1);
  const [r2, c2] = _parseNodeId(id2);
  return Math.abs(r1 - r2) + Math.abs(c1 - c2) === 1;
}

function _computeNodePositions() {
  const w = _canvas.width;
  const h = _canvas.height;
  const padX = 32, padY = 28;
  const cellW = _gridCols > 1 ? (w - 2 * padX) / (_gridCols - 1) : 0;
  const cellH = _gridRows > 1 ? (h - 2 * padY) / (_gridRows - 1) : 0;
  for (const node of Object.values(_nodes)) {
    node.x = padX + node.col * cellW;
    node.y = padY + node.row * cellH;
  }
}

function _nearestNode(mx, my, threshold = 22) {
  let best = null, bestDist = Infinity;
  for (const node of Object.values(_nodes)) {
    if (node.type === 'damaged') continue;
    const d = Math.hypot(mx - node.x, my - node.y);
    if (d < threshold && d < bestDist) {
      bestDist = d;
      best = node;
    }
  }
  return best;
}

function _canvasPos(e) {
  const rect = _canvas.getBoundingClientRect();
  const scaleX = _canvas.width / rect.width;
  const scaleY = _canvas.height / rect.height;
  return {
    x: (e.clientX - rect.left) * scaleX,
    y: (e.clientY - rect.top)  * scaleY,
  };
}

// ---------------------------------------------------------------------------
// Path-finding (client-side BFS for live feedback)
// ---------------------------------------------------------------------------

function _findPath(startId, endId) {
  // Build adjacency from existing + placed edges, excluding damaged nodes.
  const adj = {};
  for (const id of Object.keys(_nodes)) {
    if (_nodes[id].type !== 'damaged') adj[id] = [];
  }
  for (const eid of [..._existingEdges, ..._placedEdges]) {
    const [n1, n2] = _edgeToNodeIds(eid);
    if (adj[n1] !== undefined && adj[n2] !== undefined) {
      adj[n1].push(n2);
      adj[n2].push(n1);
    }
  }

  const queue = [[startId]];
  const visited = new Set([startId]);
  while (queue.length) {
    const path = queue.shift();
    const node = path[path.length - 1];
    if (node === endId) return path;
    for (const nbr of (adj[node] || [])) {
      if (!visited.has(nbr)) {
        visited.add(nbr);
        queue.push([...path, nbr]);
      }
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Interaction
// ---------------------------------------------------------------------------

function _onMouseDown(e) {
  const pos = _canvasPos(e);
  const node = _nearestNode(pos.x, pos.y);
  if (node) _dragStart = node.id;
}

function _onMouseMove(e) {
  _mousePos = _canvasPos(e);
}

function _onMouseUp(e) {
  if (!_dragStart) return;
  const pos = _canvasPos(e);
  const node = _nearestNode(pos.x, pos.y);
  if (node && node.id !== _dragStart && _areAdjacentNodes(_dragStart, node.id)) {
    _toggleEdge(_dragStart, node.id);
  }
  _dragStart = null;
}

function _onMouseLeave() {
  _dragStart = null;
}

function _toggleEdge(id1, id2) {
  const eid = _edgeId(id1, id2);
  if (!_availableEdges.has(eid)) return;  // not a placeable edge

  if (_placedEdges.has(eid)) {
    // Remove placed conduit (return it to pool).
    _placedEdges.delete(eid);
    _spareConduits++;
  } else {
    if (_spareConduits <= 0) return;
    _placedEdges.add(eid);
    _spareConduits--;
  }
  _validPath = _findPath(_sourceId, _targetId);
  _updateStatus();
}

function _updateStatus() {
  if (!_statusEl) return;
  const pathHTML = _validPath
    ? `<span class="circuit-status__path">PATH ESTABLISHED</span>`
    : `<span>NO PATH</span>`;
  const conduitsClass = _spareConduits === 0
    ? 'circuit-status__conduits--empty'
    : 'circuit-status__conduits';
  _statusEl.innerHTML = `
    ${pathHTML}
    <span class="${conduitsClass}">CONDUITS: ${_spareConduits}</span>
  `;
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

const C_PRIMARY   = '#00ff41';
const C_DIM       = '#1a3a1a';
const C_PLACED    = '#00cc88';
const C_DAMAGED   = '#ff2020';
const C_TARGET    = '#ffb000';
const C_HIGHLIGHT = '#44ffff';
const C_FLOW      = '#00ff88';

function _drawEdge(ctx, eid) {
  const [n1id, n2id] = _edgeToNodeIds(eid);
  const n1 = _nodes[n1id], n2 = _nodes[n2id];
  if (!n1 || !n2) return;
  ctx.beginPath();
  ctx.moveTo(n1.x, n1.y);
  ctx.lineTo(n2.x, n2.y);
  ctx.stroke();
}

function _drawFlow(ctx) {
  if (!_validPath || _validPath.length < 2) return;
  ctx.save();
  ctx.strokeStyle = C_FLOW;
  ctx.lineWidth = 3;
  ctx.shadowColor = C_FLOW;
  ctx.shadowBlur = 8;

  const DASH = 10, GAP = 10;
  ctx.setLineDash([DASH, GAP]);
  ctx.lineDashOffset = -(_flowOffset * (DASH + GAP));

  for (let i = 0; i < _validPath.length - 1; i++) {
    const n1 = _nodes[_validPath[i]];
    const n2 = _nodes[_validPath[i + 1]];
    if (!n1 || !n2) continue;
    ctx.beginPath();
    ctx.moveTo(n1.x, n1.y);
    ctx.lineTo(n2.x, n2.y);
    ctx.stroke();
  }

  ctx.restore();
}

function _drawNode(ctx, node) {
  const R = 11;
  const onPath  = _validPath && _validPath.includes(node.id);
  const isHighl = _highlightedNodes.has(node.id);

  ctx.beginPath();
  ctx.arc(node.x, node.y, R, 0, Math.PI * 2);

  if (node.type === 'damaged') {
    // Red circle with X.
    ctx.strokeStyle = C_DAMAGED;
    ctx.lineWidth = 1.5;
    ctx.stroke();
    const d = R * 0.55;
    ctx.beginPath();
    ctx.moveTo(node.x - d, node.y - d); ctx.lineTo(node.x + d, node.y + d);
    ctx.moveTo(node.x + d, node.y - d); ctx.lineTo(node.x - d, node.y + d);
    ctx.stroke();
    return;
  }

  if (node.type === 'source') {
    ctx.strokeStyle = C_PRIMARY;
    ctx.lineWidth = 2.5;
    ctx.stroke();
    ctx.fillStyle = 'rgba(0,255,65,0.15)';
    ctx.fill();
    ctx.fillStyle = C_PRIMARY;
    ctx.font = 'bold 10px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('SRC', node.x, node.y);
    return;
  }

  if (node.type === 'target') {
    const colour = onPath ? C_PRIMARY : C_TARGET;
    ctx.strokeStyle = colour;
    ctx.lineWidth = 2.5;
    ctx.stroke();
    ctx.fillStyle = onPath ? 'rgba(0,255,65,0.15)' : 'rgba(255,176,0,0.15)';
    ctx.fill();
    ctx.fillStyle = colour;
    ctx.font = 'bold 10px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('TGT', node.x, node.y);
    return;
  }

  // Junction node.
  let colour = '#444444';
  if (isHighl)  colour = C_HIGHLIGHT;
  else if (onPath) colour = '#006633';

  ctx.strokeStyle = colour;
  ctx.lineWidth   = isHighl ? 2 : 1.5;
  ctx.stroke();
  if (isHighl) {
    ctx.fillStyle = 'rgba(68,255,255,0.08)';
    ctx.fill();
  }
  ctx.textBaseline = 'alphabetic';
}

function _draw() {
  if (!_canvas || !_ctx) return;

  const ctx = _ctx;
  const w = _canvas.width, h = _canvas.height;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#050f05';
  ctx.fillRect(0, 0, w, h);

  // Available edges — dim dashed (potential slots).
  ctx.setLineDash([3, 7]);
  ctx.strokeStyle = C_DIM;
  ctx.lineWidth = 1.5;
  for (const eid of _availableEdges) {
    if (!_placedEdges.has(eid)) _drawEdge(ctx, eid);
  }
  ctx.setLineDash([]);

  // Existing connections — subdued solid green.
  ctx.strokeStyle = '#2a5a2a';
  ctx.lineWidth = 2;
  for (const eid of _existingEdges) _drawEdge(ctx, eid);

  // Player-placed connections.
  ctx.strokeStyle = C_PLACED;
  ctx.lineWidth = 2.5;
  for (const eid of _placedEdges) _drawEdge(ctx, eid);

  // Animated flow along the valid path (drawn on top of edges).
  _drawFlow(ctx);

  // Drag preview line.
  if (_dragStart) {
    const sn = _nodes[_dragStart];
    if (sn) {
      ctx.save();
      ctx.strokeStyle = '#88ff88';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 6]);
      ctx.beginPath();
      ctx.moveTo(sn.x, sn.y);
      ctx.lineTo(_mousePos.x, _mousePos.y);
      ctx.stroke();
      ctx.restore();
    }
  }

  // Nodes (drawn last so they appear over edge lines).
  ctx.textBaseline = 'alphabetic';
  for (const node of Object.values(_nodes)) _drawNode(ctx, node);

  // Advance flow animation offset.
  _flowOffset = (_flowOffset + 0.025) % 1;

  _rAF = requestAnimationFrame(_draw);
}

// Initialise status on first render.
requestAnimationFrame(() => _updateStatus && _updateStatus());
