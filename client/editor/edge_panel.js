/**
 * edge_panel.js — Right-panel form for editing a selected edge.
 * Also exports buildActionBuilder / getActionValue used by node_panel.
 */

import { TriggerBuilder } from "./trigger_builder.js";

const ACTION_TYPES = [
  { value: "",                     label: "— none —" },
  { value: "spawn_wave",           label: "Spawn wave" },
  { value: "start_puzzle",         label: "Start puzzle" },
  { value: "deploy_squads",        label: "Deploy squads" },
  { value: "start_boarding",       label: "Start boarding" },
  { value: "start_outbreak",       label: "Start outbreak" },
  { value: "start_fire",           label: "Start fire" },
  { value: "create_breach",        label: "Create breach" },
  { value: "apply_radiation",      label: "Apply radiation" },
  { value: "structural_damage",    label: "Structural damage" },
  { value: "contaminate_atmosphere",label: "Contaminate atmosphere" },
  { value: "system_damage",        label: "System damage" },
  { value: "crew_casualty",        label: "Crew casualty" },
  { value: "send_transmission",    label: "Send transmission" },
];

const PUZZLE_STATIONS = ["science","engineering","helm","weapons","medical","security","comms","operations","flight_ops"];
const VALID_SYSTEMS = ["engines","beams","torpedoes","shields","sensors","manoeuvring","flight_deck","ecm_suite","point_defence"];
const SEVERITY_OPTIONS = ["minor","moderate","major"];
const CHANNEL_OPTIONS = ["open","encrypted","distress"];
const CONTAMINANT_OPTIONS = ["toxic_gas","smoke","biological","chemical"];

/**
 * Render an edge edit form into containerEl.
 */
export function renderEdgePanel(container, edge, nodeRegistry, onUpdate) {
  container.innerHTML = "";
  container.classList.remove("hidden");

  const header = document.createElement("div");
  header.className = "panel-section";
  header.innerHTML = `<h3>Edge Properties</h3>
    <div style="font-size:11px;color:#4a7a9b;margin-top:4px;">
      ${edge.from} → ${edge.to}
    </div>`;
  container.appendChild(header);

  // ── Type dropdown ────────────────────────────────────────────────────────
  const typeSection = document.createElement("div");
  typeSection.className = "panel-section";
  container.appendChild(typeSection);

  const typeWrap = document.createElement("div");
  typeWrap.className = "field-group";
  typeWrap.innerHTML = `<label>Edge type</label>`;
  const typeSel = document.createElement("select");
  for (const t of ["sequence","branch_trigger"]) {
    const o = document.createElement("option");
    o.value = t; o.textContent = t;
    if (t === edge.type) o.selected = true;
    typeSel.appendChild(o);
  }
  typeWrap.appendChild(typeSel);
  typeSection.appendChild(typeWrap);

  // ── Trigger (only for branch_trigger) ───────────────────────────────────
  const trigSection = document.createElement("div");
  trigSection.className = "panel-section";
  container.appendChild(trigSection);

  let tbInstance = null;

  function renderTriggerSection() {
    trigSection.innerHTML = "";
    if (typeSel.value !== "branch_trigger") return;
    trigSection.innerHTML = `<h3>Branch Trigger</h3>`;
    const tbContainer = document.createElement("div");
    trigSection.appendChild(tbContainer);
    tbInstance = new TriggerBuilder(tbContainer, edge.trigger || null, () => {
      edge.trigger = tbInstance.getValue();
      onUpdate(edge);
    });
  }

  typeSel.addEventListener("change", () => {
    edge.type = typeSel.value;
    if (edge.type !== "branch_trigger") { edge.trigger = undefined; tbInstance = null; }
    renderTriggerSection();
    onUpdate(edge);
  });
  renderTriggerSection();

  // ── on_complete action ───────────────────────────────────────────────────
  const actionSection = document.createElement("div");
  actionSection.className = "panel-section";
  actionSection.innerHTML = `<h3>on_complete Action (optional)</h3>`;
  container.appendChild(actionSection);

  const actionContainer = document.createElement("div");
  buildActionBuilder(actionContainer, edge.on_complete || null, (val) => {
    edge.on_complete = val;
    onUpdate(edge);
  });
  actionSection.appendChild(actionContainer);

  // ── Apply ────────────────────────────────────────────────────────────────
  const applySection = document.createElement("div");
  applySection.className = "panel-section";
  const applyBtn = document.createElement("button");
  applyBtn.textContent = "Apply Changes";
  applyBtn.style.width = "100%";
  applyBtn.addEventListener("click", () => {
    edge.type = typeSel.value;
    if (tbInstance) edge.trigger = tbInstance.getValue();
    onUpdate(edge);
    _flash(applyBtn, "✓ Applied");
  });
  applySection.appendChild(applyBtn);
  container.appendChild(applySection);
}

// ---------------------------------------------------------------------------
// Action builder (shared with node_panel for on_activate)
// ---------------------------------------------------------------------------

/**
 * Build an action editing UI into container.
 * @param {HTMLElement} container
 * @param {object|null} initial
 * @param {Function} onChange — called with action dict or null
 */
export function buildActionBuilder(container, initial, onChange) {
  container.innerHTML = "";
  container.classList.add("action-builder");

  const typeSel = document.createElement("select");
  typeSel.className = "action-type-select";
  typeSel.style.cssText = "width:100%;background:#0a0f1a;border:1px solid #1e3a5f;color:#e8f4f8;padding:4px;font-family:inherit;font-size:12px;";
  for (const { value, label } of ACTION_TYPES) {
    const o = document.createElement("option");
    o.value = value; o.textContent = label;
    typeSel.appendChild(o);
  }
  if (initial?.action) typeSel.value = initial.action;
  container.appendChild(typeSel);

  const argsDiv = document.createElement("div");
  argsDiv.className = "action-args";
  container.appendChild(argsDiv);

  function renderArgs(type, init) {
    argsDiv.innerHTML = "";
    if (!type) return;

    if (type === "start_puzzle") {
      _actionField(argsDiv, "label", "text",   "Puzzle label",  init?.label || "");
      _actionField(argsDiv, "station", "select", "Station",     init?.station || "", PUZZLE_STATIONS);
      _actionField(argsDiv, "difficulty", "number", "Difficulty (1-5)", init?.difficulty || 2);
      _actionField(argsDiv, "time_limit", "number", "Time limit (s)",  init?.time_limit || 90);
    } else if (type === "spawn_wave") {
      const info = document.createElement("div");
      info.style.cssText = "font-size:11px;color:#4a7a9b;margin-top:4px;";
      info.textContent = "Use the Entity Placer (☆ Entities) to set wave enemies.";
      argsDiv.appendChild(info);
    } else if (type === "start_outbreak") {
      _actionField(argsDiv, "deck",    "text", "Deck ID",    init?.deck    || "bridge");
      _actionField(argsDiv, "pathogen","text", "Pathogen",   init?.pathogen|| "alpha");
    } else if (type === "deploy_squads") {
      const info = document.createElement("div");
      info.style.cssText = "font-size:11px;color:#4a7a9b;margin-top:4px;";
      info.textContent = "Squad deployment configured in security settings.";
      argsDiv.appendChild(info);
    } else if (type === "start_fire") {
      _actionField(argsDiv, "room_id", "text", "Room ID", init?.room_id || "");
      _actionField(argsDiv, "intensity", "number", "Intensity (1-5)", init?.intensity || 2);
    } else if (type === "create_breach") {
      _actionField(argsDiv, "room_id", "text", "Room ID", init?.room_id || "");
      _actionField(argsDiv, "severity", "select", "Severity", init?.severity || "minor", SEVERITY_OPTIONS);
    } else if (type === "apply_radiation") {
      _actionField(argsDiv, "room_id", "text", "Room ID", init?.room_id || "");
      _actionField(argsDiv, "source", "text", "Source", init?.source || "reactor");
      _actionField(argsDiv, "tier", "number", "Tier (1-4)", init?.tier || 1);
    } else if (type === "structural_damage") {
      _actionField(argsDiv, "section", "text", "Section (room ID)", init?.section || "");
      _actionField(argsDiv, "amount", "number", "Amount (1-100)", init?.amount || 10);
    } else if (type === "contaminate_atmosphere") {
      _actionField(argsDiv, "room_id", "text", "Room ID", init?.room_id || "");
      _actionField(argsDiv, "contaminant", "select", "Contaminant", init?.contaminant || "smoke", CONTAMINANT_OPTIONS);
      _actionField(argsDiv, "concentration", "number", "Concentration (0-1)", init?.concentration || 0.5);
    } else if (type === "system_damage") {
      _actionField(argsDiv, "system", "select", "System", init?.system || "engines", VALID_SYSTEMS);
      _actionField(argsDiv, "amount", "number", "Amount (1-100)", init?.amount || 10);
    } else if (type === "crew_casualty") {
      _actionField(argsDiv, "room_id", "text", "Room ID", init?.room_id || "");
      _actionField(argsDiv, "injury_type", "text", "Injury type (optional)", init?.injury_type || "");
      _actionField(argsDiv, "count", "number", "Count (1-10)", init?.count || 1);
    } else if (type === "send_transmission") {
      _actionField(argsDiv, "faction", "text", "Faction", init?.faction || "unknown");
      _actionField(argsDiv, "message", "text", "Message", init?.message || "");
      _actionField(argsDiv, "channel", "select", "Channel", init?.channel || "open", CHANNEL_OPTIONS);
    }
    fireChange();
  }

  function fireChange() {
    const type = typeSel.value;
    if (!type) { onChange(null); return; }
    const action = { action: type };
    _collectActionFields(argsDiv, type, action);
    onChange(action);
  }

  typeSel.addEventListener("change", () => renderArgs(typeSel.value, null));
  renderArgs(initial?.action || "", initial);

  return { getValue: fireChange };
}

export function getActionValue(container) {
  const typeSel = container.querySelector(".action-type-select");
  if (!typeSel || !typeSel.value) return null;
  const type = typeSel.value;
  const action = { action: type };
  _collectActionFields(container, type, action);
  return action;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Collect fields from the action form into the action dict based on type. */
function _collectActionFields(container, type, action) {
  if (type === "start_puzzle") {
    action.label      = _getField(container, "label")      || "";
    action.station    = _getField(container, "station")     || "science";
    action.difficulty = Number(_getField(container, "difficulty")) || 2;
    action.time_limit = Number(_getField(container, "time_limit")) || 90;
  } else if (type === "start_outbreak") {
    action.deck     = _getField(container, "deck")     || "bridge";
    action.pathogen = _getField(container, "pathogen") || "alpha";
  } else if (type === "start_fire") {
    action.room_id   = _getField(container, "room_id")  || "";
    action.intensity = Number(_getField(container, "intensity")) || 2;
  } else if (type === "create_breach") {
    action.room_id  = _getField(container, "room_id")  || "";
    action.severity = _getField(container, "severity")  || "minor";
  } else if (type === "apply_radiation") {
    action.room_id = _getField(container, "room_id") || "";
    action.source  = _getField(container, "source")  || "reactor";
    action.tier    = Number(_getField(container, "tier")) || 1;
  } else if (type === "structural_damage") {
    action.section = _getField(container, "section") || "";
    action.amount  = Number(_getField(container, "amount")) || 10;
  } else if (type === "contaminate_atmosphere") {
    action.room_id       = _getField(container, "room_id")       || "";
    action.contaminant   = _getField(container, "contaminant")   || "smoke";
    action.concentration = Number(_getField(container, "concentration")) || 0.5;
  } else if (type === "system_damage") {
    action.system = _getField(container, "system") || "engines";
    action.amount = Number(_getField(container, "amount")) || 10;
  } else if (type === "crew_casualty") {
    action.room_id     = _getField(container, "room_id")     || "";
    action.injury_type = _getField(container, "injury_type") || undefined;
    action.count       = Number(_getField(container, "count")) || 1;
    if (!action.injury_type) delete action.injury_type;
  } else if (type === "send_transmission") {
    action.faction = _getField(container, "faction") || "unknown";
    action.message = _getField(container, "message") || "";
    action.channel = _getField(container, "channel") || "open";
  }
}

function _actionField(parent, name, type, labelText, value, options) {
  const wrap = document.createElement("label");
  wrap.style.cssText = "display:block;font-size:11px;color:#4a7a9b;margin-bottom:3px;";
  wrap.textContent = labelText + " ";
  let el;
  if (type === "select") {
    el = document.createElement("select");
    el.style.cssText = "width:100%;background:#0a0f1a;border:1px solid #1e3a5f;color:#e8f4f8;padding:3px;font-family:inherit;font-size:11px;";
    for (const opt of (options || [])) {
      const o = document.createElement("option");
      o.value = opt; o.textContent = opt;
      if (opt === value) o.selected = true;
      el.appendChild(o);
    }
    if (value) el.value = value;
  } else {
    el = document.createElement("input");
    el.type = type;
    el.style.cssText = "width:100%;background:#0a0f1a;border:1px solid #1e3a5f;color:#e8f4f8;padding:3px;font-family:inherit;font-size:11px;";
    el.value = value ?? "";
  }
  el.dataset.actionField = name;
  wrap.appendChild(el);
  parent.appendChild(wrap);
}

function _getField(container, name) {
  return container.querySelector(`[data-action-field="${name}"]`)?.value ?? "";
}

function _flash(btn, text) {
  const orig = btn.textContent;
  btn.textContent = text;
  btn.disabled = true;
  setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 800);
}
