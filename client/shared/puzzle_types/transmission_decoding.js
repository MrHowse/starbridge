/**
 * Puzzle type: Transmission Decoding (Comms station).
 *
 * Displays a cipher with some symbol→value mappings revealed and asks the
 * player to fill in the unknown values using sum equation clues.
 *
 * exports: init, applyAssist, getSubmission, destroy
 */

let _container = null;
let _unknowns  = [];      // list of symbol codes that need values
let _revealed  = {};      // {code: value} for known symbols (from hints or assists)

export function init(container, puzzleData) {
  _container = container;
  _unknowns  = puzzleData.unknowns || [];
  _revealed  = {};

  // Build revealed map from symbols with non-null values
  for (const sym of (puzzleData.symbols || [])) {
    if (sym.value !== null && sym.value !== undefined) {
      _revealed[sym.code] = sym.value;
    }
  }

  container.innerHTML = buildHTML(puzzleData);
  wireInputs(container);
}

function buildHTML(data) {
  const knownSyms = (data.symbols || []).filter(s => s.value !== null && s.value !== undefined);
  const unknownSyms = (data.symbols || []).filter(s => s.value === null || s.value === undefined);

  const knownRows = knownSyms.map(s =>
    `<div class="cipher-row cipher-row--known">
      <span class="cipher-code">${s.code}</span>
      <span class="cipher-eq">→</span>
      <span class="cipher-value c-friendly">${s.value}</span>
    </div>`
  ).join("");

  const unknownRows = unknownSyms.map(s =>
    `<div class="cipher-row cipher-row--unknown">
      <span class="cipher-code">${s.code}</span>
      <span class="cipher-eq">→</span>
      <input type="number" class="cipher-input"
             data-code="${s.code}" min="1" max="9"
             placeholder="?" />
    </div>`
  ).join("");

  const eqRows = (data.equations || []).map(eq =>
    `<div class="eq-row">
      <span class="eq-symbols">${eq.symbols.join(" + ")}</span>
      <span class="eq-eq">= ${eq.total}</span>
    </div>`
  ).join("");

  return `
    <div class="td-layout">
      <div class="td-column td-column--known">
        <div class="td-col-header label-sm">KNOWN SYMBOLS</div>
        ${knownRows || '<p class="label-sm c-dim">None pre-decoded.</p>'}
      </div>
      <div class="td-column td-column--equations">
        <div class="td-col-header label-sm">CIPHER EQUATIONS</div>
        ${eqRows}
      </div>
      <div class="td-column td-column--unknown">
        <div class="td-col-header label-sm">DECODE (values 1–9)</div>
        ${unknownRows || '<p class="label-sm c-dim">All symbols decoded.</p>'}
      </div>
    </div>`;
}

function wireInputs(container) {
  container.querySelectorAll(".cipher-input").forEach(input => {
    input.addEventListener("input", () => {
      const v = parseInt(input.value, 10);
      if (!isNaN(v)) input.dataset.value = v;
    });
  });
}

export function applyAssist(assistData) {
  if (!_container) return;
  const { revealed_symbol: sym, value } = assistData;
  if (!sym) return;
  _revealed[sym] = value;
  // Pre-fill the input for this symbol
  const input = _container.querySelector(`[data-code="${sym}"]`);
  if (input) {
    input.value         = value;
    input.dataset.value = value;
    input.style.color   = "var(--system-warning)";
    input.readOnly      = true;
  }
}

export function getSubmission() {
  const mappings = {};
  if (!_container) return { mappings };
  _container.querySelectorAll(".cipher-input").forEach(input => {
    const code = input.dataset.code;
    const v    = parseInt(input.value, 10);
    if (code && !isNaN(v)) mappings[code] = v;
  });
  return { mappings };
}

export function destroy() {
  _container = null;
  _unknowns  = [];
  _revealed  = {};
}
