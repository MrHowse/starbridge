/**
 * graph_renderer.js — Canvas-based DAG renderer for the mission editor.
 *
 * Own coordinate system (not MapRenderer — this is a node-graph, not a world map).
 * World → canvas: canvasX = node.x * zoom + canvas.width/2 + offsetX
 * Canvas → world: worldX = (canvasX - canvas.width/2 - offsetX) / zoom
 */

export class GraphRenderer {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {object} state — shared editor state (nodes, edges, etc.)
   * @param {object} callbacks — { onSelect, onNodeMove, onEdgeCreate, onAddNode }
   */
  constructor(canvas, state, callbacks) {
    this._canvas = canvas;
    this._ctx = canvas.getContext("2d");
    this._state = state;
    this._cb = callbacks;

    this._raf = null;
    this._resize();
    window.addEventListener("resize", () => this._resize());

    canvas.addEventListener("mousedown",  e => this._onMouseDown(e));
    canvas.addEventListener("mousemove",  e => this._onMouseMove(e));
    canvas.addEventListener("mouseup",    e => this._onMouseUp(e));
    canvas.addEventListener("wheel",      e => this._onWheel(e), { passive: false });
    canvas.addEventListener("dblclick",   e => this._onDblClick(e));
    canvas.addEventListener("contextmenu", e => e.preventDefault());
  }

  // ── Public ──────────────────────────────────────────────────────────────

  draw() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = null;
      this._draw();
    });
  }

  // ── Internal: transform helpers ─────────────────────────────────────────

  _toCanvasX(wx) {
    return wx * this._state.zoom + this._canvas.width / 2 + this._state.offsetX;
  }
  _toCanvasY(wy) {
    return wy * this._state.zoom + this._canvas.height / 2 + this._state.offsetY;
  }
  _toWorldX(cx) {
    return (cx - this._canvas.width / 2 - this._state.offsetX) / this._state.zoom;
  }
  _toWorldY(cy) {
    return (cy - this._canvas.height / 2 - this._state.offsetY) / this._state.zoom;
  }

  // ── Internal: resize ────────────────────────────────────────────────────

  _resize() {
    const container = this._canvas.parentElement;
    this._canvas.width  = container.clientWidth;
    this._canvas.height = container.clientHeight;
    this.draw();
  }

  // ── Internal: draw ──────────────────────────────────────────────────────

  _draw() {
    const ctx = this._ctx;
    const w = this._canvas.width;
    const h = this._canvas.height;

    // Background
    ctx.fillStyle = "#0a0f1a";
    ctx.fillRect(0, 0, w, h);

    // Grid
    this._drawGrid(ctx, w, h);

    // Edges
    for (const edge of this._state.edges) {
      this._drawEdge(ctx, edge);
    }

    // Edge being drawn
    if (this._state.edgeDrawing) {
      const { fromId, cursorX, cursorY } = this._state.edgeDrawing;
      const fromNode = this._findNode(fromId);
      if (fromNode) {
        ctx.strokeStyle = "#00ff41";
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(this._toCanvasX(fromNode.x), this._toCanvasY(fromNode.y));
        ctx.lineTo(cursorX, cursorY);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    // Nodes
    for (const node of this._state.nodes) {
      this._drawNode(ctx, node);
    }

    // Status: node/edge count
    ctx.fillStyle = "#1e3a5f";
    ctx.font = "12px 'Courier New'";
    ctx.fillText(`nodes:${this._state.nodes.length} edges:${this._state.edges.length}  zoom:${this._state.zoom.toFixed(2)}`, 8, h - 8);
  }

  _drawGrid(ctx, w, h) {
    const spacing = 60 * this._state.zoom;
    if (spacing < 10) return;
    const startX = ((this._state.offsetX + w / 2) % spacing + spacing) % spacing;
    const startY = ((this._state.offsetY + h / 2) % spacing + spacing) % spacing;
    ctx.strokeStyle = "rgba(30,58,95,0.4)";
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    for (let x = startX; x < w; x += spacing) {
      ctx.moveTo(x, 0); ctx.lineTo(x, h);
    }
    for (let y = startY; y < h; y += spacing) {
      ctx.moveTo(0, y); ctx.lineTo(w, y);
    }
    ctx.stroke();
  }

  _drawNode(ctx, node) {
    const cx = this._toCanvasX(node.x);
    const cy = this._toCanvasY(node.y);
    const nw = 120 * this._state.zoom;
    const nh = 40  * this._state.zoom;
    const r  = 5   * this._state.zoom;

    const selected = this._state.selectedId === node.id && this._state.selectedType === "node";

    // Border colour by type
    const borderColor = _typeColor(node.type);

    ctx.save();
    // Shadow for selected
    if (selected) {
      ctx.shadowColor = borderColor;
      ctx.shadowBlur = 12;
    }

    // Fill
    ctx.fillStyle = "rgba(10,15,26,0.9)";
    _roundRect(ctx, cx - nw/2, cy - nh/2, nw, nh, r);
    ctx.fill();

    // Border
    ctx.strokeStyle = selected ? "#ffffff" : borderColor;
    ctx.lineWidth = selected ? 2 : 1;
    _roundRect(ctx, cx - nw/2, cy - nh/2, nw, nh, r);
    ctx.stroke();
    ctx.restore();

    // Type badge
    const fontSize = Math.max(8, 9 * this._state.zoom);
    ctx.font = `bold ${fontSize}px 'Courier New'`;
    ctx.fillStyle = borderColor;
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(node.type.substring(0, 3).toUpperCase(), cx - nw/2 + 4*this._state.zoom, cy - nh/2 + 4*this._state.zoom);

    // Star/check for start/victory
    const isStart   = this._state.start_node === node.id;
    const isVictory = (this._state.victory_nodes || []).includes(node.id);
    if (isStart) {
      ctx.fillStyle = "#00ff41";
      ctx.font = `${fontSize+2}px serif`;
      ctx.textAlign = "right";
      ctx.fillText("▶", cx + nw/2 - 4*this._state.zoom, cy - nh/2 + 2*this._state.zoom);
    }
    if (isVictory) {
      ctx.fillStyle = "#ffb000";
      ctx.font = `${fontSize+2}px serif`;
      ctx.textAlign = "right";
      ctx.fillText("★", cx + nw/2 - (isStart ? 16 : 4) * this._state.zoom, cy - nh/2 + 2*this._state.zoom);
    }

    // Label text
    const labelFontSize = Math.max(8, 10 * this._state.zoom);
    ctx.font = `${labelFontSize}px 'Courier New'`;
    ctx.fillStyle = "#e8f4f8";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const label = _truncate(node.text || node.id, 14);
    ctx.fillText(label, cx, cy + 4 * this._state.zoom);
  }

  _drawEdge(ctx, edge) {
    const from = this._findNode(edge.from);
    const to   = this._findNode(edge.to);
    if (!from || !to) return;

    const fx = this._toCanvasX(from.x);
    const fy = this._toCanvasY(from.y);
    const tx = this._toCanvasX(to.x);
    const ty = this._toCanvasY(to.y);

    const selected = this._state.selectedId === _edgeId(edge) && this._state.selectedType === "edge";
    const isDash = edge.type === "branch_trigger";
    const color  = selected ? "#ffffff" : (isDash ? "#ffb000" : "#00aaff");

    ctx.strokeStyle = color;
    ctx.lineWidth = selected ? 2 : 1.2;
    if (isDash) ctx.setLineDash([4 * this._state.zoom, 3 * this._state.zoom]);

    // Offset endpoints to node edge (not centre) for clarity
    const angle = Math.atan2(ty - fy, tx - fx);
    const nw = 60 * this._state.zoom;
    const nh = 20 * this._state.zoom;
    const startX = fx + Math.cos(angle) * Math.min(nw, Math.abs(Math.cos(angle)) * nw + Math.abs(Math.sin(angle)) * nh);
    const startY = fy + Math.sin(angle) * Math.min(nh, Math.abs(Math.sin(angle)) * nh + Math.abs(Math.cos(angle)) * nw);
    const endX   = tx - Math.cos(angle) * Math.min(nw, Math.abs(Math.cos(angle)) * nw + Math.abs(Math.sin(angle)) * nh);
    const endY   = ty - Math.sin(angle) * Math.min(nh, Math.abs(Math.sin(angle)) * nh + Math.abs(Math.cos(angle)) * nw);

    // Bezier control points (curve away from straight line)
    const dist = Math.hypot(endX - startX, endY - startY);
    const cpOffset = Math.min(60, dist * 0.3) * this._state.zoom;
    const cp1x = startX + Math.cos(angle - 0.5) * cpOffset;
    const cp1y = startY + Math.sin(angle - 0.5) * cpOffset;
    const cp2x = endX   - Math.cos(angle + 0.5) * cpOffset;
    const cp2y = endY   - Math.sin(angle + 0.5) * cpOffset;

    ctx.beginPath();
    ctx.moveTo(startX, startY);
    ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, endX, endY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Arrowhead
    _arrow(ctx, endX, endY, angle, 8 * this._state.zoom, color);

    // Trigger label for branch_trigger
    if (isDash && edge.trigger) {
      const midX = (startX + endX) / 2;
      const midY = (startY + endY) / 2;
      const fontSize = Math.max(8, 9 * this._state.zoom);
      ctx.font = `${fontSize}px 'Courier New'`;
      ctx.fillStyle = "#ffb000";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(_triggerSummary(edge.trigger), midX, midY - 8 * this._state.zoom);
    }
  }

  // ── Hit testing ─────────────────────────────────────────────────────────

  hitTestNode(mx, my) {
    for (const node of [...this._state.nodes].reverse()) {
      const cx = this._toCanvasX(node.x);
      const cy = this._toCanvasY(node.y);
      const hw = 60 * this._state.zoom;
      const hh = 22 * this._state.zoom;
      if (Math.abs(mx - cx) < hw && Math.abs(my - cy) < hh) return node.id;
    }
    return null;
  }

  hitTestEdge(mx, my) {
    for (const edge of this._state.edges) {
      const from = this._findNode(edge.from);
      const to   = this._findNode(edge.to);
      if (!from || !to) continue;
      const fx = this._toCanvasX(from.x);
      const fy = this._toCanvasY(from.y);
      const tx = this._toCanvasX(to.x);
      const ty = this._toCanvasY(to.y);
      const midX = (fx + tx) / 2;
      const midY = (fy + ty) / 2;
      if (Math.abs(mx - midX) < 20 && Math.abs(my - midY) < 20) return _edgeId(edge);
    }
    return null;
  }

  // ── Mouse events ─────────────────────────────────────────────────────────

  _onMouseDown(e) {
    const { mx, my } = _mousePos(e, this._canvas);
    const nodeId = this.hitTestNode(mx, my);

    if (e.ctrlKey && nodeId) {
      // Start edge drawing
      this._state.edgeDrawing = { fromId: nodeId, cursorX: mx, cursorY: my };
      this._canvas.style.cursor = "crosshair";
      return;
    }

    if (nodeId) {
      // Start drag
      const node = this._findNode(nodeId);
      this._state.dragging = {
        id: nodeId,
        origX: node.x, origY: node.y,
        startMX: mx, startMY: my,
      };
      this._cb.onSelect(nodeId, "node");
      this.draw();
      return;
    }

    const edgeId = this.hitTestEdge(mx, my);
    if (edgeId) {
      this._cb.onSelect(edgeId, "edge");
      this.draw();
      return;
    }

    // Pan
    this._panning = { startX: mx, startY: my, ox: this._state.offsetX, oy: this._state.offsetY };
    this._cb.onSelect(null, null);
    this.draw();
  }

  _onMouseMove(e) {
    const { mx, my } = _mousePos(e, this._canvas);

    if (this._state.edgeDrawing) {
      this._state.edgeDrawing.cursorX = mx;
      this._state.edgeDrawing.cursorY = my;
      this.draw();
      return;
    }

    if (this._state.dragging) {
      const d = this._state.dragging;
      const dx = (mx - d.startMX) / this._state.zoom;
      const dy = (my - d.startMY) / this._state.zoom;
      const node = this._findNode(d.id);
      if (node) {
        node.x = d.origX + dx;
        node.y = d.origY + dy;
        this.draw();
      }
      return;
    }

    if (this._panning) {
      const dx = mx - this._panning.startX;
      const dy = my - this._panning.startY;
      this._state.offsetX = this._panning.ox + dx;
      this._state.offsetY = this._panning.oy + dy;
      this.draw();
      return;
    }

    // Cursor hint
    const hoverNode = this.hitTestNode(mx, my);
    this._canvas.style.cursor = hoverNode
      ? (e.ctrlKey ? "crosshair" : "grab")
      : "default";
  }

  _onMouseUp(e) {
    const { mx, my } = _mousePos(e, this._canvas);

    if (this._state.edgeDrawing) {
      const { fromId } = this._state.edgeDrawing;
      const toId = this.hitTestNode(mx, my);
      if (toId && toId !== fromId) {
        this._cb.onEdgeCreate(fromId, toId);
      }
      this._state.edgeDrawing = null;
      this._canvas.style.cursor = "default";
      this.draw();
      return;
    }

    if (this._state.dragging) {
      this._cb.onNodeMove(this._state.dragging.id);
      this._state.dragging = null;
      this._canvas.style.cursor = "default";
      this.draw();
      return;
    }

    this._panning = null;
  }

  _onWheel(e) {
    e.preventDefault();
    const { mx, my } = _mousePos(e, this._canvas);
    const factor = e.deltaY < 0 ? 1.15 : (1 / 1.15);
    const newZoom = Math.max(0.1, Math.min(4, this._state.zoom * factor));

    // Zoom centred on cursor
    const wx = this._toWorldX(mx);
    const wy = this._toWorldY(my);
    this._state.zoom = newZoom;
    this._state.offsetX = mx - wx * newZoom - this._canvas.width / 2;
    this._state.offsetY = my - wy * newZoom - this._canvas.height / 2;
    this.draw();
  }

  _onDblClick(e) {
    const { mx, my } = _mousePos(e, this._canvas);
    const wx = this._toWorldX(mx);
    const wy = this._toWorldY(my);
    this._cb.onAddNode("objective", wx, wy);
  }

  // ── Helpers ──────────────────────────────────────────────────────────────

  _findNode(id) {
    return this._state.nodes.find(n => n.id === id) || null;
  }
}

// ---------------------------------------------------------------------------
// Canvas drawing utilities
// ---------------------------------------------------------------------------

function _roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function _arrow(ctx, x, y, angle, size, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x - Math.cos(angle - 0.4) * size, y - Math.sin(angle - 0.4) * size);
  ctx.lineTo(x - Math.cos(angle + 0.4) * size, y - Math.sin(angle + 0.4) * size);
  ctx.closePath();
  ctx.fill();
}

function _typeColor(type) {
  return {
    objective:   "#00ff41",
    parallel:    "#00aaff",
    branch:      "#ffb000",
    conditional: "#ff2020",
    checkpoint:  "#ffffff",
  }[type] || "#4a7a9b";
}

function _truncate(str, maxLen) {
  if (!str) return "";
  return str.length > maxLen ? str.substring(0, maxLen - 1) + "…" : str;
}

function _triggerSummary(trigger) {
  if (!trigger) return "";
  const t = trigger.type || "";
  if (t === "timer_elapsed") return `⏱${trigger.seconds}s`;
  if (t === "all_enemies_destroyed") return "⚔all";
  if (t === "wave_defeated") return `wave:${trigger.enemy_prefix || "?"}`;
  if (t === "entity_destroyed") return `💥${trigger.target || "?"}`;
  if (t === "puzzle_completed" || t === "puzzle_resolved") return `🧩${trigger.puzzle_label || "?"}`;
  if (t === "all_of") return "ALL";
  if (t === "any_of") return "ANY";
  return t.substring(0, 8);
}

function _edgeId(edge) {
  return `${edge.from}→${edge.to}`;
}

function _mousePos(e, canvas) {
  const rect = canvas.getBoundingClientRect();
  return { mx: e.clientX - rect.left, my: e.clientY - rect.top };
}
