/**
 * node_panel.js — Right-panel form for editing a selected node.
 *
 * Exports: renderNodePanel(containerEl, node, state, onUpdate)
 */

import { TriggerBuilder } from "./trigger_builder.js";
import { buildActionBuilder, getActionValue } from "./edge_panel.js";

/**
 * Render a node edit form into containerEl.
 * @param {HTMLElement} container
 * @param {object} node — the node dict from state.nodes
 * @param {object} state — editor state (for start_node/victory_nodes)
 * @param {Function} onUpdate — called with updated node dict
 */
export function renderNodePanel(container, node, state, onUpdate) {
  container.innerHTML = "";
  container.classList.remove("hidden");

  // ── Header ──────────────────────────────────────────────────────────────
  const h2 = document.createElement("div");
  h2.className = "panel-section";
  const typeBadge = `<span class="type-badge type-${node.type}">${node.type}</span>`;
  h2.innerHTML = `<h3>Node Properties ${typeBadge}</h3>`;
  container.appendChild(h2);

  // ── Core fields ─────────────────────────────────────────────────────────
  const coreSection = document.createElement("div");
  coreSection.className = "panel-section";
  container.appendChild(coreSection);

  // ID (readonly after creation)
  coreSection.appendChild(_field("ID", "text", node.id, true, "node-id"));

  // Text / label
  const textField = _textarea("Label / Text", node.text || "", "node-text");
  coreSection.appendChild(textField);

  // Type selector
  const typeWrap = document.createElement("div");
  typeWrap.className = "field-group";
  typeWrap.innerHTML = `<label>Type</label>`;
  const typeSel = document.createElement("select");
  for (const t of ["objective","parallel","branch","conditional","checkpoint"]) {
    const opt = document.createElement("option");
    opt.value = t; opt.textContent = t;
    if (t === node.type) opt.selected = true;
    typeSel.appendChild(opt);
  }
  typeSel.addEventListener("change", () => {
    node.type = typeSel.value;
    renderNodePanel(container, node, state, onUpdate);
    onUpdate(node);
  });
  typeWrap.appendChild(typeSel);
  coreSection.appendChild(typeWrap);

  // Start node / victory node checkboxes
  const cbStart = _checkbox("Set as start_node", state.start_node === node.id, "cb-start");
  cbStart.querySelector("input").addEventListener("change", e => {
    if (e.target.checked) state.start_node = node.id;
    onUpdate(node);
  });
  coreSection.appendChild(cbStart);

  const isVictory = (state.victory_nodes || []).includes(node.id);
  const cbVictory = _checkbox("Victory node", isVictory, "cb-victory");
  cbVictory.querySelector("input").addEventListener("change", e => {
    if (!state.victory_nodes) state.victory_nodes = [];
    if (e.target.checked) {
      if (!state.victory_nodes.includes(node.id)) state.victory_nodes.push(node.id);
    } else {
      state.victory_nodes = state.victory_nodes.filter(id => id !== node.id);
    }
    onUpdate(node);
  });
  coreSection.appendChild(cbVictory);

  // ── Type-specific fields ─────────────────────────────────────────────────
  if (node.type === "objective" || node.type === "checkpoint") {
    _renderTriggerSection(container, node, onUpdate);
  }

  if (node.type === "parallel") {
    _renderParallelSection(container, node, onUpdate);
  }

  if (node.type === "conditional") {
    _renderConditionalSection(container, node, onUpdate);
  }

  // ── Save / apply ─────────────────────────────────────────────────────────
  const saveSection = document.createElement("div");
  saveSection.className = "panel-section";
  const applyBtn = document.createElement("button");
  applyBtn.textContent = "Apply Changes";
  applyBtn.style.width = "100%";
  applyBtn.addEventListener("click", () => {
    node.text = container.querySelector("#node-text")?.value || "";
    onUpdate(node);
    _flash(applyBtn, "✓ Applied");
  });
  saveSection.appendChild(applyBtn);
  container.appendChild(saveSection);
}

// ---------------------------------------------------------------------------
// Sub-sections
// ---------------------------------------------------------------------------

function _renderTriggerSection(container, node, onUpdate) {
  const sec = document.createElement("div");
  sec.className = "panel-section";
  sec.innerHTML = `<h3>Trigger (completes this node)</h3>`;
  container.appendChild(sec);

  const tbContainer = document.createElement("div");
  sec.appendChild(tbContainer);

  const tb = new TriggerBuilder(tbContainer, node.trigger || null, () => {
    node.trigger = tb.getValue();
    onUpdate(node);
  });
}

function _renderParallelSection(container, node, onUpdate) {
  const sec = document.createElement("div");
  sec.className = "panel-section";
  sec.innerHTML = `<h3>Parallel Settings</h3>`;
  container.appendChild(sec);

  // complete_when
  const cw = document.createElement("div");
  cw.className = "field-group";
  cw.innerHTML = `<label>Complete when</label>`;
  const cwSel = document.createElement("select");
  for (const v of ["all","any","count"]) {
    const o = document.createElement("option");
    o.value = v; o.textContent = v;
    if (v === (node.complete_when || "all")) o.selected = true;
    cwSel.appendChild(o);
  }
  cw.appendChild(cwSel);
  sec.appendChild(cw);

  // count field (shown when "count" selected)
  const countWrap = document.createElement("div");
  countWrap.className = "field-group";
  countWrap.innerHTML = `<label>Count</label>`;
  const countInp = document.createElement("input");
  countInp.type = "number";
  countInp.min = "1";
  countInp.value = node.count || 1;
  countWrap.appendChild(countInp);
  sec.appendChild(countWrap);

  const updateCountVisibility = () => {
    countWrap.style.display = cwSel.value === "count" ? "block" : "none";
  };
  updateCountVisibility();
  cwSel.addEventListener("change", () => {
    node.complete_when = cwSel.value;
    updateCountVisibility();
    onUpdate(node);
  });
  countInp.addEventListener("input", () => {
    node.count = parseInt(countInp.value) || 1;
    onUpdate(node);
  });

  // Children list (read-only info — children are nested nodes)
  const children = node.children || [];
  const childInfo = document.createElement("div");
  childInfo.style.cssText = "font-size:11px;color:#4a7a9b;margin-top:8px;";
  childInfo.textContent = `Children: ${children.length} (add via palette, then drag into this parallel node)`;
  sec.appendChild(childInfo);
}

function _renderConditionalSection(container, node, onUpdate) {
  const sec = document.createElement("div");
  sec.className = "panel-section";
  sec.innerHTML = `<h3>Conditional Settings</h3>`;
  container.appendChild(sec);

  // condition trigger
  const condLabel = document.createElement("div");
  condLabel.className = "field-group";
  condLabel.innerHTML = `<label>Activation condition</label>`;
  const condContainer = document.createElement("div");
  condLabel.appendChild(condContainer);
  sec.appendChild(condLabel);

  new TriggerBuilder(condContainer, node.condition || null, () => {
    // Rebuilt each render; value read at apply time
  });

  // deactivate_when trigger
  const deactLabel = document.createElement("div");
  deactLabel.className = "field-group";
  deactLabel.innerHTML = `<label>Deactivate when (optional)</label>`;
  const deactContainer = document.createElement("div");
  deactLabel.appendChild(deactContainer);
  sec.appendChild(deactLabel);

  new TriggerBuilder(deactContainer, node.deactivate_when || null, () => {});

  // on_activate action
  const onActLabel = document.createElement("div");
  onActLabel.className = "field-group";
  onActLabel.innerHTML = `<label>on_activate action (optional)</label>`;
  const onActContainer = document.createElement("div");
  buildActionBuilder(onActContainer, node.on_activate || null, (v) => {
    node.on_activate = v;
    onUpdate(node);
  });
  onActLabel.appendChild(onActContainer);
  sec.appendChild(onActLabel);
}

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------

function _field(labelText, type, value, readonly, id) {
  const wrap = document.createElement("div");
  wrap.className = "field-group";
  const lbl = document.createElement("label");
  lbl.textContent = labelText;
  const inp = document.createElement("input");
  inp.type = type;
  inp.value = value || "";
  if (readonly) inp.readOnly = true;
  if (id) inp.id = id;
  wrap.appendChild(lbl);
  wrap.appendChild(inp);
  return wrap;
}

function _textarea(labelText, value, id) {
  const wrap = document.createElement("div");
  wrap.className = "field-group";
  const lbl = document.createElement("label");
  lbl.textContent = labelText;
  const ta = document.createElement("textarea");
  ta.rows = 2;
  ta.value = value;
  if (id) ta.id = id;
  wrap.appendChild(lbl);
  wrap.appendChild(ta);
  return wrap;
}

function _checkbox(labelText, checked, id) {
  const wrap = document.createElement("div");
  wrap.className = "checkbox-row";
  const inp = document.createElement("input");
  inp.type = "checkbox";
  inp.checked = checked;
  if (id) inp.id = id;
  const lbl = document.createElement("label");
  lbl.textContent = labelText;
  lbl.htmlFor = id || "";
  wrap.appendChild(inp);
  wrap.appendChild(lbl);
  return wrap;
}

function _flash(btn, text) {
  const orig = btn.textContent;
  btn.textContent = text;
  btn.disabled = true;
  setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 800);
}
