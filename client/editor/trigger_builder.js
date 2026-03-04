/**
 * trigger_builder.js — Dropdown-driven trigger JSON builder.
 *
 * Usage:
 *   const tb = new TriggerBuilder(containerEl, initialTrigger, onChange);
 *   tb.getValue()  // → trigger dict or null
 */

const TRIGGER_GROUPS = [
  { label: null, items: [
    { value: "",                    label: "— select trigger —" },
  ]},
  { label: "Timer", items: [
    { value: "timer_elapsed",       label: "Timer elapsed" },
  ]},
  { label: "Spatial", items: [
    { value: "player_in_area",      label: "Player in area" },
  ]},
  { label: "Entity", items: [
    { value: "entity_destroyed",    label: "Entity destroyed" },
    { value: "wave_defeated",       label: "Wave defeated" },
    { value: "all_enemies_destroyed", label: "All enemies destroyed" },
    { value: "scan_completed",      label: "Scan completed" },
  ]},
  { label: "Hull", items: [
    { value: "ship_hull_below",     label: "Ship hull below %" },
    { value: "ship_hull_above",     label: "Ship hull above %" },
    { value: "ship_hull_zero",      label: "Ship hull zero" },
    { value: "player_hull_zero",    label: "Player hull zero" },
  ]},
  { label: "Station", items: [
    { value: "station_hull_below",       label: "Station hull below %" },
    { value: "station_destroyed",        label: "Station destroyed" },
    { value: "station_captured",         label: "Station captured" },
    { value: "station_sensor_jammed",    label: "Station sensor jammed" },
    { value: "station_reinforcements_called", label: "Station reinforcements called" },
    { value: "component_destroyed",      label: "Component destroyed" },
  ]},
  { label: "Creature", items: [
    { value: "creature_state",              label: "Creature state" },
    { value: "creature_destroyed",          label: "Creature destroyed" },
    { value: "creature_study_complete",     label: "Creature study complete" },
    { value: "creature_communication_complete", label: "Creature comm complete" },
    { value: "no_creatures_type",           label: "No creatures of type" },
  ]},
  { label: "Signal", items: [
    { value: "signal_located",      label: "Signal located" },
  ]},
  { label: "Proximity", items: [
    { value: "proximity_with_shields", label: "Proximity with shields" },
  ]},
  { label: "Puzzle", items: [
    { value: "puzzle_completed",    label: "Puzzle completed" },
    { value: "puzzle_resolved",     label: "Puzzle resolved (either)" },
    { value: "puzzle_failed",       label: "Puzzle failed" },
  ]},
  { label: "Training", items: [
    { value: "training_flag",       label: "Training flag" },
  ]},
  { label: "Boarding", items: [
    { value: "boarding_active",     label: "Boarding active" },
    { value: "no_intruders",        label: "No intruders" },
  ]},
  { label: "Compound", items: [
    { value: "all_of",              label: "All of (compound)" },
    { value: "any_of",              label: "Any of (compound)" },
    { value: "none_of",             label: "None of (compound)" },
  ]},
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
  wave_defeated:        [{ name: "prefix", type: "text", label: "Enemy prefix" }],
  all_enemies_destroyed: [],
  puzzle_completed:     [{ name: "label", type: "text", label: "Puzzle label" }],
  puzzle_resolved:      [{ name: "label", type: "text", label: "Puzzle label" }],
  puzzle_failed:        [{ name: "label", type: "text", label: "Puzzle label" }],
  scan_completed:       [{ name: "target", type: "text", label: "Entity ID / target" }],
  ship_hull_below:      [{ name: "value", type: "number", label: "Hull % threshold", default: 50 }],
  ship_hull_above:      [{ name: "value", type: "number", label: "Hull % threshold", default: 50 }],
  ship_hull_zero:       [],
  player_hull_zero:     [],
  boarding_active:      [],
  no_intruders:         [],
  // Station triggers
  station_hull_below:   [
    { name: "station_id", type: "text", label: "Station ID" },
    { name: "threshold", type: "number", label: "Hull % threshold", default: 50 },
  ],
  station_destroyed:    [{ name: "station_id", type: "text", label: "Station ID" }],
  station_captured:     [{ name: "station_id", type: "text", label: "Station ID" }],
  station_sensor_jammed:[{ name: "station_id", type: "text", label: "Station ID" }],
  station_reinforcements_called: [{ name: "station_id", type: "text", label: "Station ID" }],
  component_destroyed:  [{ name: "component_id", type: "text", label: "Component ID" }],
  // Creature triggers
  creature_state:       [
    { name: "creature_id", type: "text", label: "Creature ID" },
    { name: "state", type: "select", label: "State",
      options: ["passive", "aggressive", "fleeing", "studying", "communicating"] },
  ],
  creature_destroyed:   [{ name: "creature_id", type: "text", label: "Creature ID" }],
  creature_study_complete:        [{ name: "creature_id", type: "text", label: "Creature ID" }],
  creature_communication_complete:[{ name: "creature_id", type: "text", label: "Creature ID" }],
  no_creatures_type:    [{ name: "creature_type", type: "text", label: "Creature type" }],
  // Signal
  signal_located:       [],
  // Proximity
  proximity_with_shields: [
    { name: "x", type: "number", label: "World X", default: 50000 },
    { name: "y", type: "number", label: "World Y", default: 50000 },
    { name: "radius", type: "number", label: "Radius", default: 5000 },
    { name: "min_shield", type: "number", label: "Min shield %", default: 50 },
    { name: "duration", type: "number", label: "Duration (s)", default: 5 },
  ],
  // Training
  training_flag:        [{ name: "flag", type: "text", label: "Flag name" }],
  // Compound
  all_of:               [],
  any_of:               [],
  none_of:              [],
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

    if (type === "all_of" || type === "any_of" || type === "none_of") {
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

    // Type selector with optgroups
    const sel = document.createElement("select");
    sel.className = "trigger-type-select";
    sel.style.width = "100%";
    sel.style.background = "#0a0f1a";
    sel.style.border = "1px solid #1e3a5f";
    sel.style.color = "#e8f4f8";
    sel.style.padding = "4px";
    sel.style.fontFamily = "inherit";
    sel.style.fontSize = "12px";

    for (const group of TRIGGER_GROUPS) {
      if (group.label === null) {
        // Top-level options (the placeholder)
        for (const { value, label } of group.items) {
          const opt = document.createElement("option");
          opt.value = value;
          opt.textContent = label;
          sel.appendChild(opt);
        }
      } else {
        const optgroup = document.createElement("optgroup");
        optgroup.label = group.label;
        for (const { value, label } of group.items) {
          const opt = document.createElement("option");
          opt.value = value;
          opt.textContent = label;
          optgroup.appendChild(opt);
        }
        sel.appendChild(optgroup);
      }
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

    if (type === "all_of" || type === "any_of" || type === "none_of") {
      this._renderCompound(type, initial);
    } else {
      const fields = TRIGGER_FIELDS[type] || [];
      for (const field of fields) {
        const wrap = document.createElement("label");
        wrap.textContent = field.label + " ";
        let inp;
        if (field.type === "select" && field.options) {
          inp = document.createElement("select");
          inp.style.cssText = "width:100%;background:#0a0f1a;border:1px solid #1e3a5f;color:#e8f4f8;padding:3px;font-family:inherit;font-size:11px;";
          for (const optVal of field.options) {
            const o = document.createElement("option");
            o.value = optVal; o.textContent = optVal;
            inp.appendChild(o);
          }
          if (initial && initial[field.name] !== undefined) inp.value = initial[field.name];
        } else {
          inp = document.createElement("input");
          inp.type = field.type === "number" ? "number" : "text";
          inp.style.cssText = "width:100%;background:#0a0f1a;border:1px solid #1e3a5f;color:#e8f4f8;padding:3px;font-family:inherit;font-size:11px;";
          if (initial && initial[field.name] !== undefined) {
            inp.value = initial[field.name];
          } else if (field.default !== undefined) {
            inp.value = field.default;
          }
        }
        inp.dataset.field = field.name;
        inp.addEventListener("input", () => this._onChange());
        inp.addEventListener("change", () => this._onChange());
        wrap.appendChild(inp);
        this._argsEl.appendChild(wrap);
      }
    }
    this._onChange();
  }

  _renderCompound(type, initial) {
    const header = document.createElement("div");
    header.style.cssText = "font-size:11px;color:#4a7a9b;margin-bottom:4px;";
    const labels = {
      all_of: "All of the following must be true:",
      any_of: "Any of the following must be true:",
      none_of: "None of the following must be true:",
    };
    header.textContent = labels[type] || "";
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
