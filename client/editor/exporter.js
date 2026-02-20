/**
 * exporter.js — Assembles the final mission JSON from editor state.
 *
 * The editor stores nodes in a flat list (parallel children have parentId).
 * This module reconstructs the nested graph format expected by MissionGraph.
 */

/**
 * Build the complete mission dict from editor state.
 * @param {object} state — editor state
 * @returns {object} mission dict in graph format
 */
export function exportMission(state) {
  // Separate top-level nodes from parallel children
  const childMap = {};  // parentId → [child, ...]
  const topLevel = [];

  for (const node of state.nodes) {
    if (node.parentId) {
      if (!childMap[node.parentId]) childMap[node.parentId] = [];
      childMap[node.parentId].push(node);
    } else {
      topLevel.push(node);
    }
  }

  // Build node dicts, embedding children into parallel nodes
  const nodes = topLevel.map(n => _buildNodeDict(n, childMap));

  // Build edge dicts (strip UI-only fields)
  const edges = state.edges.map(e => _buildEdgeDict(e));

  // Build spawn list from state.spawn
  const spawn = (state.spawn || []).map(s => ({ ...s }));

  const mission = {
    id:              state.id || "unnamed",
    name:            state.name || "Unnamed Mission",
    briefing:        state.briefing || "",
    spawn,
    nodes,
    edges,
    start_node:      state.start_node || null,
    victory_nodes:   state.victory_nodes || [],
    defeat_condition: state.defeat_condition || null,
  };

  // Remove null/empty optional fields
  if (!mission.briefing) delete mission.briefing;
  if (!mission.spawn.length) delete mission.spawn;
  if (!mission.defeat_condition) delete mission.defeat_condition;

  return mission;
}

/**
 * Download a JSON file in the browser.
 * @param {object} mission
 */
export function downloadMission(mission) {
  const json = JSON.stringify(mission, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = `${mission.id || "mission"}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _buildNodeDict(node, childMap) {
  const dict = {
    id:   node.id,
    type: node.type,
    text: node.text || "",
  };

  if (node.trigger)         dict.trigger         = node.trigger;
  if (node.condition)       dict.condition       = node.condition;
  if (node.deactivate_when) dict.deactivate_when = node.deactivate_when;
  if (node.on_activate)     dict.on_activate     = node.on_activate;
  if (node.on_deactivate)   dict.on_deactivate   = node.on_deactivate;

  if (node.type === "parallel") {
    dict.complete_when = node.complete_when || "all";
    if (node.complete_when === "count" && node.count) dict.count = node.count;
    // Embed children
    const children = childMap[node.id] || [];
    dict.children = children.map(c => _buildNodeDict(c, childMap));
  }

  return dict;
}

function _buildEdgeDict(edge) {
  const dict = {
    from: edge.from,
    to:   edge.to,
    type: edge.type || "sequence",
  };
  if (edge.trigger)     dict.trigger     = edge.trigger;
  if (edge.on_complete) dict.on_complete = edge.on_complete;
  return dict;
}
