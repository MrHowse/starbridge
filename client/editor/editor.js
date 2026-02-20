/**
 * editor.js — Main orchestrator for the Starbridge Mission Editor.
 *
 * Manages editor state, toolbar actions, and coordinates between
 * graph_renderer, node_panel, edge_panel, validator, and exporter.
 *
 * Uses plain fetch() for all server calls. No WebSocket.
 */

import { GraphRenderer }        from "./graph_renderer.js";
import { renderNodePanel }      from "./node_panel.js";
import { renderEdgePanel }      from "./edge_panel.js";
import { runValidation }        from "./validator.js";
import { exportMission, downloadMission } from "./exporter.js";
import { initEntityPlacer }     from "./entity_placer.js";

// ---------------------------------------------------------------------------
// Editor state
// ---------------------------------------------------------------------------

const state = {
  id:              "",
  name:            "",
  briefing:        "",
  spawn:           [],
  defeat_condition: null,

  nodes:           [],    // flat list; parallel children have parentId property
  edges:           [],

  start_node:      null,
  victory_nodes:   [],

  // UI state
  selectedId:      null,
  selectedType:    null,   // "node" | "edge"
  offsetX:         0,
  offsetY:         0,
  zoom:            1.0,
  dragging:        null,   // {id, startMX, startMY, origX, origY}
  edgeDrawing:     null,   // {fromId, cursorX, cursorY}
};

let _renderer = null;
let _nodeCounter = 1;

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  const canvas = document.getElementById("graph-canvas");
  _renderer = new GraphRenderer(canvas, state, {
    onSelect:     _selectItem,
    onNodeMove:   () => _renderer.draw(),
    onEdgeCreate: _createEdge,
    onAddNode:    _addNodeAt,
  });

  _bindToolbar();
  _bindMetaInputs();
  initEntityPlacer(state);

  newMission();
  _setStatus("New mission created. Add nodes with the palette or double-click the canvas.");
});

// ---------------------------------------------------------------------------
// Toolbar bindings
// ---------------------------------------------------------------------------

function _bindToolbar() {
  document.getElementById("btn-new").addEventListener("click", () => {
    if (state.nodes.length > 0 && !confirm("Discard current mission?")) return;
    newMission();
  });

  document.getElementById("btn-open").addEventListener("click", _toggleOpenDropdown);
  document.getElementById("btn-save").addEventListener("click", saveMission);
  document.getElementById("btn-validate").addEventListener("click", () => {
    validateMission();
    document.getElementById("validation-panel").classList.remove("hidden");
  });
  document.getElementById("btn-export").addEventListener("click", () => {
    downloadMission(exportMission(state));
    _setStatus("Mission exported as JSON file.");
  });
  document.getElementById("btn-test").addEventListener("click", testMission);
  document.getElementById("btn-delete").addEventListener("click", deleteSelected);

  // Palette node type buttons
  document.querySelectorAll(".palette-btn[data-type]").forEach(btn => {
    btn.addEventListener("click", () => addNode(btn.dataset.type));
  });
}

function _bindMetaInputs() {
  document.getElementById("meta-id").addEventListener("input", e => {
    state.id = e.target.value.trim();
  });
  document.getElementById("meta-name").addEventListener("input", e => {
    state.name = e.target.value;
  });
  document.getElementById("meta-start").addEventListener("input", e => {
    state.start_node = e.target.value.trim() || null;
    _renderer.draw();
  });
  document.getElementById("meta-victory").addEventListener("input", e => {
    state.victory_nodes = e.target.value.split(",").map(s => s.trim()).filter(Boolean);
    _renderer.draw();
  });
  document.getElementById("meta-briefing").addEventListener("input", e => {
    state.briefing = e.target.value;
  });
}

// ---------------------------------------------------------------------------
// Core actions
// ---------------------------------------------------------------------------

export function newMission() {
  state.id = "";
  state.name = "";
  state.briefing = "";
  state.spawn = [];
  state.defeat_condition = null;
  state.nodes = [];
  state.edges = [];
  state.start_node = null;
  state.victory_nodes = [];
  state.selectedId = null;
  state.selectedType = null;
  state.offsetX = 0;
  state.offsetY = 0;
  state.zoom = 1.0;
  _nodeCounter = 1;

  _syncMetaUI();
  _hidePanel("node-panel");
  _hidePanel("edge-panel");
  _hidePanel("validation-panel");
  document.getElementById("panel-placeholder").classList.remove("hidden");
  document.getElementById("btn-delete").disabled = true;
  if (_renderer) _renderer.draw();
  _setStatus("New mission.");
  _updateNodeCount();
}

export async function openMission(id) {
  try {
    const r = await fetch(`/editor/mission/${encodeURIComponent(id)}`);
    if (!r.ok) { _setStatus(`Error: ${r.status} ${r.statusText}`); return; }
    const data = await r.json();
    _loadMission(data);
    _setStatus(`Opened: ${data.name || id}`);
  } catch (err) {
    _setStatus(`Failed to load: ${err}`);
  }
}

export async function saveMission() {
  const mission = exportMission(state);
  if (!mission.id) {
    alert("Enter a mission ID before saving.");
    document.getElementById("meta-id").focus();
    return;
  }
  try {
    const r = await fetch("/editor/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(mission),
    });
    const data = await r.json();
    if (r.ok && data.saved) {
      _setStatus(`Saved: ${data.file}${data.warnings.length ? ` (${data.warnings.length} warning(s))` : ""}`);
      if (data.warnings.length > 0) {
        document.getElementById("validation-panel").classList.remove("hidden");
        document.getElementById("validation-results").innerHTML =
          data.warnings.map(w => `<div class="error">⚠ ${_esc(w)}</div>`).join("");
      }
    } else {
      _setStatus(`Save failed: ${data.detail || JSON.stringify(data)}`);
    }
  } catch (err) {
    _setStatus(`Save error: ${err}`);
  }
}

export async function validateMission() {
  const mission = exportMission(state);
  const valid = await runValidation(mission);
  _setStatus(valid ? "✓ Mission is valid." : "⚠ Validation errors found — see panel.");
  return valid;
}

export function testMission() {
  const mission = exportMission(state);
  localStorage.setItem("starbridge_test_mission", JSON.stringify(mission));
  window.open("/client/briefing/?test=1", "_blank");
  _setStatus("Mission sent to test tab.");
}

export function addNode(type, x, y) {
  const id = `${type}_${_nodeCounter++}`;
  const node = {
    id,
    type,
    text: `${_capitalize(type)} ${_nodeCounter - 1}`,
    x: x ?? (_nodeCounter * 60 - state.nodes.length * 20),
    y: y ?? 0,
  };
  if (type === "objective") node.trigger = null;
  if (type === "parallel") { node.complete_when = "all"; node.children = []; }
  state.nodes.push(node);

  // Auto-set start node if first node
  if (state.nodes.length === 1) {
    state.start_node = id;
    document.getElementById("meta-start").value = id;
  }

  _renderer.draw();
  _updateNodeCount();
  _selectItem(id, "node");
  _setStatus(`Added ${type} node '${id}'`);
}

function _addNodeAt(type, wx, wy) {
  addNode(type, wx, wy);
}

function _createEdge(fromId, toId) {
  // Avoid duplicate edges
  const exists = state.edges.some(e => e.from === fromId && e.to === toId);
  if (exists) { _setStatus("Edge already exists."); return; }

  const edge = { from: fromId, to: toId, type: "sequence" };
  state.edges.push(edge);
  _renderer.draw();
  _selectItem(`${fromId}→${toId}`, "edge");
  _setStatus(`Edge created: ${fromId} → ${toId}`);
}

export function deleteSelected() {
  if (!state.selectedId) return;
  if (state.selectedType === "node") {
    state.nodes = state.nodes.filter(n => n.id !== state.selectedId);
    state.edges = state.edges.filter(e => e.from !== state.selectedId && e.to !== state.selectedId);
    if (state.start_node === state.selectedId) state.start_node = null;
    state.victory_nodes = (state.victory_nodes || []).filter(id => id !== state.selectedId);
    _syncMetaUI();
  } else if (state.selectedType === "edge") {
    const [from, to] = state.selectedId.split("→");
    state.edges = state.edges.filter(e => !(e.from === from && e.to === to));
  }
  _selectItem(null, null);
  _renderer.draw();
  _updateNodeCount();
  _setStatus("Deleted.");
}

function _selectItem(id, type) {
  state.selectedId   = id;
  state.selectedType = type;

  document.getElementById("btn-delete").disabled = !id;
  document.getElementById("panel-placeholder").classList.toggle("hidden", !!id);

  if (type === "node") {
    _hidePanel("edge-panel");
    const node = state.nodes.find(n => n.id === id);
    if (node) {
      renderNodePanel(
        document.getElementById("node-panel"),
        node,
        state,
        _onNodeUpdated,
      );
    }
  } else if (type === "edge") {
    _hidePanel("node-panel");
    const [from, to] = (id || "").split("→");
    const edge = state.edges.find(e => e.from === from && e.to === to);
    if (edge) {
      renderEdgePanel(
        document.getElementById("edge-panel"),
        edge,
        _nodeRegistry(),
        _onEdgeUpdated,
      );
    }
  } else {
    _hidePanel("node-panel");
    _hidePanel("edge-panel");
  }

  if (_renderer) _renderer.draw();
}

function _onNodeUpdated(node) {
  // Update state.nodes in place (already mutated by panel)
  _syncMetaUI();
  _renderer.draw();
}

function _onEdgeUpdated(edge) {
  _renderer.draw();
}

// ---------------------------------------------------------------------------
// Open dropdown
// ---------------------------------------------------------------------------

async function _toggleOpenDropdown() {
  const dd = document.getElementById("open-dropdown");
  const isVisible = !dd.classList.contains("hidden");
  if (isVisible) { dd.classList.add("hidden"); return; }

  dd.innerHTML = `<div class="dropdown-item" style="color:#4a7a9b">Loading…</div>`;
  dd.classList.remove("hidden");

  try {
    const r = await fetch("/editor/missions");
    const { missions } = await r.json();
    dd.innerHTML = "";
    if (missions.length === 0) {
      dd.innerHTML = `<div class="dropdown-item" style="color:#4a7a9b">No missions found</div>`;
    } else {
      for (const m of missions) {
        const item = document.createElement("div");
        item.className = "dropdown-item";
        item.textContent = `${m.name} (${m.id})`;
        item.addEventListener("click", () => {
          dd.classList.add("hidden");
          openMission(m.id);
        });
        dd.appendChild(item);
      }
    }
  } catch (err) {
    dd.innerHTML = `<div class="dropdown-item" style="color:#ff2020">Error: ${err}</div>`;
  }

  // Close on outside click
  const close = (e) => {
    if (!dd.contains(e.target) && e.target.id !== "btn-open") {
      dd.classList.add("hidden");
      document.removeEventListener("click", close);
    }
  };
  setTimeout(() => document.addEventListener("click", close), 10);
}

// ---------------------------------------------------------------------------
// Load mission from dict
// ---------------------------------------------------------------------------

function _loadMission(data) {
  newMission();

  state.id      = data.id      || "";
  state.name    = data.name    || "";
  state.briefing = data.briefing || "";
  state.spawn   = data.spawn   || [];
  state.defeat_condition = data.defeat_condition || null;
  state.start_node   = data.start_node  || null;
  state.victory_nodes = data.victory_nodes || [];

  // Flatten nodes (parallel children get parentId)
  _flattenNodes(data.nodes || [], null);

  // Load edges
  state.edges = (data.edges || []).map(e => ({ ...e }));

  // Auto-layout if nodes lack positions
  _autoLayout();

  _syncMetaUI();
  _renderer.draw();
  _updateNodeCount();
}

function _flattenNodes(nodes, parentId) {
  let x = 0;
  for (const node of nodes) {
    const flat = { ...node, x: node._editorX || 0, y: node._editorY || 0 };
    if (parentId) flat.parentId = parentId;
    // Don't include children in the flat node
    delete flat.children;
    state.nodes.push(flat);
    // Recurse children
    if (node.type === "parallel" && node.children?.length) {
      _flattenNodes(node.children, node.id);
    }
    x++;
    _nodeCounter = Math.max(_nodeCounter, parseInt(node.id.split("_").pop() || 0) + 1);
  }
}

function _autoLayout() {
  // BFS from start_node for top-level layout
  const assigned = new Set();
  const byId = Object.fromEntries(state.nodes.map(n => [n.id, n]));

  let col = 0, row = 0;
  const queue = state.start_node ? [state.start_node] : [];
  const visited = new Set();

  while (queue.length) {
    const id = queue.shift();
    if (visited.has(id)) continue;
    visited.add(id);
    const node = byId[id];
    if (!node || node.parentId) continue;  // skip children

    if (!node.x && !node.y) {
      node.x = col * 180 - 360;
      node.y = row * 80;
      col++;
      if (col > 4) { col = 0; row++; }
    }
    assigned.add(id);

    // Queue successors
    for (const e of state.edges) {
      if (e.from === id && !visited.has(e.to)) queue.push(e.to);
    }
  }

  // Position any remaining nodes
  for (const node of state.nodes) {
    if (!assigned.has(node.id) && !node.parentId && !node.x && !node.y) {
      node.x = col * 180 - 360;
      node.y = row * 80;
      col++;
    }
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _nodeRegistry() {
  return Object.fromEntries(state.nodes.map(n => [n.id, n]));
}

function _syncMetaUI() {
  document.getElementById("meta-id").value      = state.id || "";
  document.getElementById("meta-name").value    = state.name || "";
  document.getElementById("meta-start").value   = state.start_node || "";
  document.getElementById("meta-victory").value = (state.victory_nodes || []).join(",");
  document.getElementById("meta-briefing").value = state.briefing || "";
}

function _hidePanel(id) {
  const el = document.getElementById(id);
  if (el) { el.innerHTML = ""; el.classList.add("hidden"); }
}

function _setStatus(msg) {
  document.getElementById("status-msg").textContent = msg;
}

function _updateNodeCount() {
  const topLevel = state.nodes.filter(n => !n.parentId).length;
  const children = state.nodes.filter(n =>  n.parentId).length;
  document.getElementById("node-count").textContent =
    `${topLevel} nodes${children ? ` (+${children} children)` : ""} · ${state.edges.length} edges`;
}

function _capitalize(str) {
  return str ? str.charAt(0).toUpperCase() + str.slice(1) : str;
}

function _esc(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
