/**
 * entity_placer.js — Star-chart canvas for entity/spawn placement.
 *
 * Manages a 100k × 100k world canvas overlaid as a modal panel.
 * Updates state.spawn with placed entities.
 */

const WORLD_SIZE = 100_000;
const ENTITY_COLORS = {
  station:           "#00aaff",
  scout:             "#ff2020",
  cruiser:           "#ffb000",
  destroyer:         "#ff6600",
  frigate:           "#ff6644",
  corvette:          "#ffdd00",
  battleship:        "#cc0033",
  enemy_station:     "#ff00ff",
  creature:          "#ffaa00",
  hazard_nebula:     "#8844ff",
  hazard_minefield:  "#ff2020",
  hazard_radiation:  "#00ff41",
};

// Entity types that use triangle shapes (enemies)
const _TRIANGLE_TYPES = new Set(["scout", "cruiser", "destroyer", "frigate", "corvette", "battleship"]);
// Diamond shape
const _DIAMOND_TYPES = new Set(["enemy_station"]);
// Organic circle (creature)
const _ORGANIC_TYPES = new Set(["creature"]);

let _canvas, _ctx, _state, _pendingPos;

export function initEntityPlacer(state) {
  _state = state;
  _canvas = document.getElementById("entity-canvas");
  _ctx = _canvas.getContext("2d");

  // Resize canvas to fill the overlay
  _resizeCanvas();

  _canvas.addEventListener("click",     _onCanvasClick);
  _canvas.addEventListener("mousemove", _onCanvasMouseMove);

  document.getElementById("entity-add-btn").addEventListener("click", _onAddEntity);
  document.getElementById("entity-placer-close").addEventListener("click", _close);
  document.getElementById("btn-entity-placer").addEventListener("click", _open);

  // Toggle type-specific fields when entity type changes
  const typeSelect = document.getElementById("entity-type-select");
  if (typeSelect) {
    typeSelect.addEventListener("change", () => _toggleTypeFields(typeSelect.value));
    _toggleTypeFields(typeSelect.value);
  }

  _drawEntities();
}

function _open() {
  document.getElementById("entity-placer-overlay").classList.remove("hidden");
  _resizeCanvas();
  _drawEntities();
}

function _close() {
  document.getElementById("entity-placer-overlay").classList.add("hidden");
  _pendingPos = null;
}

function _resizeCanvas() {
  const overlay = document.getElementById("entity-placer-overlay");
  // Canvas fills the overlay minus header, toolbar, list
  _canvas.width  = overlay.clientWidth;
  _canvas.height = Math.max(300, overlay.clientHeight - 120);
  _drawEntities();
}

// World ↔ canvas
function _worldToCanvas(wx, wy) {
  const sx = (_canvas.width  - 40) / WORLD_SIZE;
  const sy = (_canvas.height - 40) / WORLD_SIZE;
  return { cx: 20 + wx * sx, cy: 20 + wy * sy };
}

function _canvasToWorld(cx, cy) {
  const sx = (_canvas.width  - 40) / WORLD_SIZE;
  const sy = (_canvas.height - 40) / WORLD_SIZE;
  return { wx: (cx - 20) / sx, wy: (cy - 20) / sy };
}

function _drawEntities() {
  if (!_canvas || !_ctx) return;
  const ctx = _ctx;
  ctx.fillStyle = "#0a0f1a";
  ctx.fillRect(0, 0, _canvas.width, _canvas.height);

  // Grid
  ctx.strokeStyle = "rgba(30,58,95,0.3)";
  ctx.lineWidth = 0.5;
  const step = 10000;
  const sx = (_canvas.width - 40) / WORLD_SIZE;
  const sy = (_canvas.height - 40) / WORLD_SIZE;
  for (let wx = 0; wx <= WORLD_SIZE; wx += step) {
    const cx = 20 + wx * sx;
    ctx.beginPath(); ctx.moveTo(cx, 20); ctx.lineTo(cx, _canvas.height - 20); ctx.stroke();
  }
  for (let wy = 0; wy <= WORLD_SIZE; wy += step) {
    const cy = 20 + wy * sy;
    ctx.beginPath(); ctx.moveTo(20, cy); ctx.lineTo(_canvas.width - 20, cy); ctx.stroke();
  }

  // Entities
  for (const entity of (_state.spawn || [])) {
    const { cx, cy } = _worldToCanvas(entity.x || 0, entity.y || 0);
    const color = ENTITY_COLORS[entity.type] || "#4a7a9b";
    ctx.fillStyle = color;
    ctx.beginPath();
    if (_TRIANGLE_TYPES.has(entity.type)) {
      // Triangle (pointing up) for enemy ships
      ctx.moveTo(cx, cy - 7);
      ctx.lineTo(cx - 6, cy + 5);
      ctx.lineTo(cx + 6, cy + 5);
      ctx.closePath();
      ctx.fill();
    } else if (_DIAMOND_TYPES.has(entity.type)) {
      // Diamond for enemy stations
      ctx.moveTo(cx, cy - 8);
      ctx.lineTo(cx + 6, cy);
      ctx.lineTo(cx, cy + 8);
      ctx.lineTo(cx - 6, cy);
      ctx.closePath();
      ctx.fill();
    } else if (_ORGANIC_TYPES.has(entity.type)) {
      // Organic wobbly circle for creatures
      ctx.arc(cx, cy, 7, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(cx - 2, cy - 2, 3, 0, Math.PI * 2);
      ctx.stroke();
    } else {
      // Default circle for stations, hazards, etc.
      ctx.arc(cx, cy, 6, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = "#e8f4f8";
    ctx.font = "12px 'Courier New'";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(entity.id || entity.type, cx + 9, cy);
  }

  // Pending position indicator
  if (_pendingPos) {
    const { cx, cy } = _worldToCanvas(_pendingPos.wx, _pendingPos.wy);
    ctx.strokeStyle = "#00ff41";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(cx, cy, 8, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(cx - 10, cy); ctx.lineTo(cx + 10, cy);
    ctx.moveTo(cx, cy - 10); ctx.lineTo(cx, cy + 10);
    ctx.stroke();
  }
}

function _onCanvasClick(e) {
  const rect = _canvas.getBoundingClientRect();
  const cx = e.clientX - rect.left;
  const cy = e.clientY - rect.top;
  const { wx, wy } = _canvasToWorld(cx, cy);
  _pendingPos = { wx: Math.round(wx), wy: Math.round(wy) };
  document.getElementById("entity-coords").textContent =
    `X: ${_pendingPos.wx.toLocaleString()}  Y: ${_pendingPos.wy.toLocaleString()}`;
  _drawEntities();
}

function _onCanvasMouseMove(e) {
  const rect = _canvas.getBoundingClientRect();
  const cx = e.clientX - rect.left;
  const cy = e.clientY - rect.top;
  const { wx, wy } = _canvasToWorld(cx, cy);
  document.getElementById("entity-coords").textContent =
    `X: ${Math.round(wx).toLocaleString()}  Y: ${Math.round(wy).toLocaleString()}`;
}

function _onAddEntity() {
  const type = document.getElementById("entity-type-select").value;
  const id   = document.getElementById("entity-id-input").value.trim();
  if (!id) { alert("Enter an entity ID first."); return; }
  if (!_pendingPos) { alert("Click on the map first to choose a position."); return; }

  if (!_state.spawn) _state.spawn = [];
  const entry = { type, id, x: _pendingPos.wx, y: _pendingPos.wy };
  // Type-specific fields
  const variantEl = document.getElementById("entity-variant-select");
  if (variantEl && !variantEl.parentElement.classList.contains("hidden") && type === "enemy_station") {
    entry.variant = variantEl.value;
  }
  const creatureTypeEl = document.getElementById("entity-creature-type-select");
  if (creatureTypeEl && !creatureTypeEl.parentElement.classList.contains("hidden") && type === "creature") {
    entry.creature_type = creatureTypeEl.value;
  }
  _state.spawn.push(entry);

  document.getElementById("entity-id-input").value = "";
  _pendingPos = null;
  _refreshEntityList();
  _drawEntities();
}

function _refreshEntityList() {
  const list = document.getElementById("entity-list");
  list.innerHTML = "";
  for (let i = 0; i < (_state.spawn || []).length; i++) {
    const e = _state.spawn[i];
    const row = document.createElement("div");
    row.className = "entity-list-item";
    row.innerHTML = `<span style="color:${ENTITY_COLORS[e.type] || '#4a7a9b'}">${e.type}</span>
      <span style="margin:0 6px;">${e.id}</span>
      <span style="color:#4a7a9b">(${e.x}, ${e.y})</span>`;
    const rm = document.createElement("button");
    rm.textContent = "✕";
    rm.addEventListener("click", () => {
      _state.spawn.splice(i, 1);
      _refreshEntityList();
      _drawEntities();
    });
    row.appendChild(rm);
    list.appendChild(row);
  }
}

function _toggleTypeFields(type) {
  const variantWrap = document.getElementById("entity-variant-wrap");
  const creatureWrap = document.getElementById("entity-creature-type-wrap");
  if (variantWrap) variantWrap.classList.toggle("hidden", type !== "enemy_station");
  if (creatureWrap) creatureWrap.classList.toggle("hidden", type !== "creature");
}
