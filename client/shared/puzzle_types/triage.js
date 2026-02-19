/**
 * Puzzle type: Triage (Medical station).
 *
 * Displays patient cards with symptom lists. The player identifies the
 * pathogen from the symptoms and selects the treatment steps in the
 * correct order. A Medical Reference panel shows the symptom→pathogen table.
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
let _patients   = [];   // [{id, symptoms, pathogen|null}, ...]
let _available_pathogens   = [];
let _available_treatments  = [];

// Per-patient submission state: {patient_id: {pathogen, treatment_steps[3]}}
let _diagnoses = {};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * @param {HTMLElement} container
 * @param {Object} puzzleData
 */
export function init(container, puzzleData) {
  _container = container;
  _patients              = puzzleData.patients || [];
  _available_pathogens   = puzzleData.available_pathogens || [];
  _available_treatments  = puzzleData.available_treatments || [];

  // Initialise submission state
  _diagnoses = {};
  for (const p of _patients) {
    _diagnoses[p.id] = {
      pathogen:        p.pathogen || '',
      treatment_steps: ['', '', ''],
    };
  }

  container.innerHTML = _buildHTML();
  _wireInputs(container);
}

/**
 * Apply Science pathogen-analysis assist.
 * assistData: { patient_id, pathogen }
 */
export function applyAssist(assistData) {
  if (!_container) return;
  const { patient_id: pid, pathogen } = assistData;
  if (!pid || !pathogen) return;

  _diagnoses[pid].pathogen = pathogen;

  // Update the pathogen select in the DOM
  const select = _container.querySelector(`[data-patient="${pid}"] .triage-pathogen-select`);
  if (select) {
    select.value = pathogen;
    select.style.color = 'var(--system-warning)';
    // Brief highlight
    const card = _container.querySelector(`[data-patient="${pid}"]`);
    if (card) {
      card.style.borderColor = 'var(--system-warning)';
      setTimeout(() => { if (card) card.style.borderColor = ''; }, 2000);
    }
  }
}

/** Return the player's current diagnosis state as a submission payload. */
export function getSubmission() {
  const diagnoses = {};
  for (const [pid, d] of Object.entries(_diagnoses)) {
    diagnoses[pid] = {
      pathogen:        d.pathogen,
      treatment_steps: d.treatment_steps.filter(Boolean),
    };
  }
  return { diagnoses };
}

/** Clean up. */
export function destroy() {
  _container = null;
  _patients   = [];
  _diagnoses  = {};
}

// ---------------------------------------------------------------------------
// HTML builder
// ---------------------------------------------------------------------------

function _buildHTML() {
  const patientCards = _patients.map(p => _buildPatientCard(p)).join('');

  return `
    <div class="triage-layout">
      <div class="triage-patients">
        ${patientCards}
      </div>
    </div>`;
}

function _buildPatientCard(patient) {
  const pid = patient.id;
  const label = pid.replace('_', ' ').toUpperCase();
  const symptoms = (patient.symptoms || [])
    .map(s => `<span class="triage-symptom">${s.replace(/_/g, ' ')}</span>`)
    .join('');

  // Pathogen select — pre-filled if pre-diagnosed
  const pathogenOptions = _available_pathogens
    .map(p => `<option value="${p}" ${patient.pathogen === p ? 'selected' : ''}>${p}</option>`)
    .join('');

  // Treatment step selects (3 in order)
  const stepSelects = [0, 1, 2].map(i => {
    const stepOptions = ['', ..._available_treatments]
      .map(t => `<option value="${t}">${t ? t.replace(/_/g, ' ') : '— select —'}</option>`)
      .join('');
    return `
      <div class="triage-step-row">
        <span class="text-label triage-step-num">STEP ${i + 1}</span>
        <select class="triage-step-select" data-step="${i}">
          ${stepOptions}
        </select>
      </div>`;
  }).join('');

  return `
    <div class="triage-card" data-patient="${pid}">
      <div class="triage-card__header text-label">${label}</div>
      <div class="triage-symptoms">${symptoms}</div>
      <div class="triage-diagnosis">
        <div class="triage-field-row">
          <span class="text-label">PATHOGEN</span>
          <select class="triage-pathogen-select" ${patient.pathogen ? 'style="color:var(--system-warning)"' : ''}>
            <option value="">— identify —</option>
            ${pathogenOptions}
          </select>
        </div>
        <div class="triage-treatment-label text-label">TREATMENT SEQUENCE</div>
        ${stepSelects}
      </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Input wiring
// ---------------------------------------------------------------------------

function _wireInputs(container) {
  // Pathogen selects
  container.querySelectorAll('.triage-pathogen-select').forEach(sel => {
    const card = sel.closest('[data-patient]');
    const pid  = card?.dataset.patient;
    if (!pid) return;
    // Set initial value from pre-diagnosed state
    const preDiag = _patients.find(p => p.id === pid)?.pathogen;
    if (preDiag) sel.value = preDiag;

    sel.addEventListener('change', () => {
      _diagnoses[pid].pathogen = sel.value;
    });
  });

  // Treatment step selects
  container.querySelectorAll('.triage-step-select').forEach(sel => {
    const card = sel.closest('[data-patient]');
    const pid  = card?.dataset.patient;
    const step = parseInt(sel.dataset.step, 10);
    if (!pid || isNaN(step)) return;

    sel.addEventListener('change', () => {
      _diagnoses[pid].treatment_steps[step] = sel.value;
    });
  });
}
