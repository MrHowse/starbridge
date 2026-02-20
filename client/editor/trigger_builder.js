/**
 * trigger_builder.js — Dropdown-driven trigger JSON builder.
 *
 * Usage:
 *   const tb = new TriggerBuilder(containerEl, initialTrigger, onChange);
 *   tb.getValue()  // → trigger dict or null
 */

const TRIGGER_TYPES = [
  { value: "",                    label: "— select trigger —" },
  { value: "timer_elapsed",       label: "Timer elapsed" },
  { value: "player_in_area",      label: "Player in area" },
  { value: "entity_destroyed",    label: "Entity destroyed" },
  { value: "wave_defeated",       label: "Wave defeated" },
  { value: "all_enemies_destroyed", label: "All enemies destroyed" },
  { value: "puzzle_completed",    label: "Puzzle completed" },
  { value: "puzzle_resolved",     label: "Puzzle resolved (either)" },
  { value: "puzzle_failed",       label: "Puzzle failed" },
  { value: "scan_completed",      label: "Scan completed" },
  { value: "ship_hull_below",     label: "Ship hull below %" },
  { value: "ship_hull_above",     label: "Ship hull above %" },
  { value: "boarding_active",     label: "Boarding active" },
  { value: "no_intruders",        label: "No intruders" },
  { value: "all_of",              label: "All of (compound)" },
  { value: "any_of",              label: "Any of (compound)" },
];

// Fields required for each trigger type: [{name, type, label, default?}]
const TRIGGER_FIELDS = {
  timer_elapsed:        [{ name: "seconds", type: "number", label: "Seconds", default: 10 }],
  player_in_area:       [
    { name: "x", type: "number", label: "World X", default: 50000 },
    { name: "y", type: "number", label: "World Y", default: 50000 },
    { name: "r", type: "number", label: "Radius",  default: 5000  },
  ],
  entity_destroyed:     [{ name: "target", type: "text", label: "Entity ID" }],
  wave_defeated:        [{ name: "enemy_prefix", type: "text", label: "Enemy prefix" }],
  all_enemies_destroyed: [],
  puzzle_completed:     [{ name: "puzzle_label", type: "text", label: "Puzzle label" }],
  puzzle_resolved:      [{ name: "puzzle_label", type: "text", label: "Puzzle label" }],
  puzzle_failed:        [{ name: "puzzle_label", type: "text", label: "Puzzle label" }],
  scan_completed:       [{ name: "target", type: "text", label: "Entity ID / target" }],
  ship_hull_below:      [{ name: "value", type: "number", label: "Hull % threshold", default: 50 }],
  ship_hull_above:      [{ name: "value", type: "number", label: "Hull % threshold", default: 50 }],
  boarding_active:      [],
  no_intruders:         [],
  all_of:               [],  // handled by compound UI
  any_of:               [],
};

export class TriggerBuilder {
  /**
   * @param {HTMLElement} container — element to render into
   * @param {object|null} initial — initial trigger dict
   * @param {Function} onChange — called with new trigger dict whenever value changes
   */
  constructor(container, initial, onChange) {
    this._container = container;
    this._onChange = onChange || (() => {});
    this._compounds = [];  // list of TriggerBuilder instances for nested triggers
    this._render(initial || null);
  }

  getValue() {
    const type = this._typeEl ? this._typeEl.value : "";
    if (!type) return null;

    const result = { type };

    if (type === "all_of" || type === "any_of") {
      result.triggers = this._compounds.map(c => c.getValue()).filter(Boolean);
      return result;
    }

    const fields = TRIGGER_FIELDS[type] || [];
    for (const field of fields) {
      const el = this._container.querySelector(`[data-field="${field.name}"]`);
      if (!el) continue;
      const raw = el.value.trim();
      if (field.type === "number") {
        result[field.name] = raw === "" ? (field.default ?? 0) : Number(raw);
      } else {
        result[field.name] = raw;
      }
    }
    return result;
  }

  _render(initial) {
    this._container.innerHTML = "";
    this._container.classList.add("trigger-builder");

    // Type selector
    const sel = document.createElement("select");
    sel.className = "trigger-type-select";
    sel.style.width = "100%";
    sel.style.background = "#0a0f1a";
    sel.style.border = "1px solid #1e3a5f";
    sel.style.color = "#e8f4f8";
    sel.style.padding = "4px";
    sel.style.fontFamily = "inherit";
    sel.style.fontSize = "12px";

    for (const { value, label } of TRIGGER_TYPES) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      sel.appendChild(opt);
    }
    if (initial?.type) sel.value = initial.type;
    this._typeEl = sel;

    sel.addEventListener("change", () => this._onTypeChange(sel.value));
    this._container.appendChild(sel);

    // Args area
    this._argsEl = document.createElement("div");
    this._argsEl.className = "trigger-args";
    this._container.appendChild(this._argsEl);

    if (initial?.type) this._onTypeChange(initial.type, initial);
  }

  _onTypeChange(type, initial) {
    this._argsEl.innerHTML = "";
    this._compounds = [];

    if (!type) { this._onChange(); return; }

    if (type === "all_of" || type === "any_of") {
      this._renderCompound(type, initial);
    } else {
      const fields = TRIGGER_FIELDS[type] || [];
      for (const field of fields) {
        const wrap = document.createElement("label");
        wrap.textContent = field.label + " ";
        const inp = document.createElement("input");
        inp.type = field.type === "number" ? "number" : "text";
        inp.dataset.field = field.name;
        inp.style.cssText = "width:100%;background:#0a0f1a;border:1px solid #1e3a5f;color:#e8f4f8;padding:3px;font-family:inherit;font-size:11px;";
        if (initial && initial[field.name] !== undefined) {
          inp.value = initial[field.name];
        } else if (field.default !== undefined) {
          inp.value = field.default;
        }
        inp.addEventListener("input", () => this._onChange());
        wrap.appendChild(inp);
        this._argsEl.appendChild(wrap);
      }
    }
    this._onChange();
  }

  _renderCompound(type, initial) {
    const header = document.createElement("div");
    header.style.cssText = "font-size:11px;color:#4a7a9b;margin-bottom:4px;";
    header.textContent = type === "all_of"
      ? "All of the following must be true:"
      : "Any of the following must be true:";
    this._argsEl.appendChild(header);

    this._compoundList = document.createElement("div");
    this._compoundList.className = "compound-triggers";
    this._argsEl.appendChild(this._compoundList);

    const addBtn = document.createElement("button");
    addBtn.textContent = "+ Add sub-trigger";
    addBtn.className = "add-compound-btn";
    addBtn.type = "button";
    addBtn.addEventListener("click", () => this._addCompoundItem(null));
    this._argsEl.appendChild(addBtn);

    // Restore existing nested triggers
    const nested = initial?.triggers || [];
    for (const t of nested) this._addCompoundItem(t);
    if (nested.length === 0) this._addCompoundItem(null);
  }

  _addCompoundItem(initial) {
    const wrap = document.createElement("div");
    wrap.className = "compound-trigger-item";

    const removeBtn = document.createElement("button");
    removeBtn.className = "compound-trigger-remove";
    removeBtn.type = "button";
    removeBtn.textContent = "✕";
    removeBtn.addEventListener("click", () => {
      const idx = this._compounds.indexOf(child);
      if (idx !== -1) this._compounds.splice(idx, 1);
      wrap.remove();
      this._onChange();
    });
    wrap.appendChild(removeBtn);

    const inner = document.createElement("div");
    wrap.appendChild(inner);
    this._compoundList.appendChild(wrap);

    const child = new TriggerBuilder(inner, initial, () => this._onChange());
    this._compounds.push(child);
  }
}
