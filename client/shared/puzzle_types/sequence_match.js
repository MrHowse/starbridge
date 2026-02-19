/**
 * Puzzle type: Sequence Match (proof-of-concept)
 *
 * Renders N coloured buttons. The player clicks them in order to build a
 * sequence and submits it. An assist pre-fills the first N items.
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
let _clicked = [];         // player's current sequence
let _revealed = [];        // pre-revealed items from assist
let _length = 0;           // total sequence length

// Colour definitions (must match server COLOURS list).
const COLOUR_META = {
  red:    { label: 'RED',    cls: 'seq-btn--red'    },
  blue:   { label: 'BLUE',   cls: 'seq-btn--blue'   },
  green:  { label: 'GREEN',  cls: 'seq-btn--green'  },
  yellow: { label: 'YELLOW', cls: 'seq-btn--yellow' },
};

// ---------------------------------------------------------------------------
// Interface
// ---------------------------------------------------------------------------

/**
 * Initialise the puzzle UI inside the given container div.
 * @param {HTMLElement} container
 * @param {Object} puzzleData — { type, length, colours, revealed, revealed_sequence }
 */
export function init(container, puzzleData) {
  _container = container;
  _clicked = [];
  _length = puzzleData.length;
  _revealed = puzzleData.revealed_sequence || [];

  // Pre-fill clicked with any revealed items from the initial generate().
  _clicked = [..._revealed];

  _render();
}

/**
 * Apply an assist payload. Updates revealed items and re-renders.
 * @param {Object} assistData — { revealed, revealed_sequence }
 */
export function applyAssist(assistData) {
  if (assistData.revealed_sequence) {
    _revealed = assistData.revealed_sequence;
    // Keep player's extra clicks beyond the revealed portion.
    const extra = _clicked.slice(_revealed.length);
    _clicked = [..._revealed, ...extra];
    _render();
  }
}

/**
 * Return the player's current submission.
 * @returns {{ sequence: string[] }}
 */
export function getSubmission() {
  return { sequence: [..._clicked] };
}

/** Remove all DOM created by this module. */
export function destroy() {
  if (_container) _container.innerHTML = '';
  _container = null;
  _clicked = [];
  _revealed = [];
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _render() {
  if (!_container) return;
  _container.innerHTML = '';

  // ── Colour buttons ──────────────────────────────────────────────────────
  const buttonsDiv = document.createElement('div');
  buttonsDiv.className = 'seq-buttons';

  for (const colour of Object.keys(COLOUR_META)) {
    const btn = document.createElement('button');
    const meta = COLOUR_META[colour];
    btn.className = `seq-btn ${meta.cls}`;
    btn.textContent = meta.label;
    btn.addEventListener('click', () => _onColourClick(colour));
    buttonsDiv.appendChild(btn);
  }
  _container.appendChild(buttonsDiv);

  // ── Answer track ─────────────────────────────────────────────────────────
  const label = document.createElement('p');
  label.className = 'seq-answer-label text-dim text-label';
  label.style.marginTop = '0.75rem';
  label.textContent = `YOUR SEQUENCE (${_clicked.length}/${_length}):`;
  _container.appendChild(label);

  const answerDiv = document.createElement('div');
  answerDiv.className = 'seq-answer';

  for (let i = 0; i < _length; i++) {
    const pip = document.createElement('div');
    const isRevealed = i < _revealed.length;
    const colour = _clicked[i];

    pip.className = `seq-answer-pip${colour ? ` seq-answer-pip--${colour}` : ''}${isRevealed ? ' seq-answer-pip--revealed' : ''}`;
    pip.title = colour ? colour : '';
    answerDiv.appendChild(pip);
  }
  _container.appendChild(answerDiv);

  // ── Undo button ───────────────────────────────────────────────────────────
  if (_clicked.length > _revealed.length) {
    const undoBtn = document.createElement('button');
    undoBtn.className = 'fire-btn fire-btn--small';
    undoBtn.style.marginTop = '0.5rem';
    undoBtn.style.width = '100%';
    undoBtn.textContent = 'UNDO LAST';
    undoBtn.addEventListener('click', _onUndo);
    _container.appendChild(undoBtn);
  }
}

// ---------------------------------------------------------------------------
// Interaction
// ---------------------------------------------------------------------------

function _onColourClick(colour) {
  if (_clicked.length >= _length) return;  // sequence full
  _clicked.push(colour);
  _render();
}

function _onUndo() {
  if (_clicked.length > _revealed.length) {
    _clicked.pop();
    _render();
  }
}
