/**
 * Puzzle type: Frequency Matching (Science)
 *
 * Oscilloscope canvas shows target (amber) and player (green) composite
 * waveforms.  Per-component frequency and amplitude sliders update the
 * player waveform in real time.  A match-quality meter with a threshold
 * marker shows how close the player is to solving.
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
let _canvas    = null;
let _ctx       = null;

let _componentCount = 0;
let _targetComponents   = [];  // [{amplitude, frequency}, ...]
let _playerComponents   = [];  // [{amplitude, frequency}, ...] — mutable
let _tolerance  = 0.30;

// DOM refs
let _meterFill      = null;
let _meterThreshold = null;
let _meterEl        = null;

// Render loop
let _rAF = null;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * @param {HTMLElement} container
 * @param {Object} puzzleData
 */
export function init(container, puzzleData) {
  _container = container;

  const {
    component_count, target_components,
    tolerance, initial_player_components,
  } = puzzleData;

  _componentCount     = component_count;
  _targetComponents   = target_components.map(c => ({ ...c }));
  _playerComponents   = initial_player_components.map(c => ({ ...c }));
  _tolerance          = tolerance;

  // ── Oscilloscope canvas ─────────────────────────────────────────────────
  _canvas = document.createElement('canvas');
  _canvas.className = 'freq-scope';
  _canvas.height = 90;
  container.appendChild(_canvas);
  _ctx = _canvas.getContext('2d');

  // ── Match-quality meter ─────────────────────────────────────────────────
  _meterEl = document.createElement('div');
  _meterEl.className = 'freq-meter';

  const track = document.createElement('div');
  track.className = 'freq-meter__track';

  _meterFill = document.createElement('div');
  _meterFill.className = 'freq-meter__fill';
  _meterFill.style.width = '0%';
  track.appendChild(_meterFill);

  _meterThreshold = document.createElement('div');
  _meterThreshold.className = 'freq-meter__threshold';
  _meterThreshold.style.left = `${(1 - _tolerance) * 100}%`;
  track.appendChild(_meterThreshold);

  _meterEl.appendChild(track);

  const label = document.createElement('div');
  label.className = 'freq-meter__label';
  label.innerHTML = `<span>MATCH</span><span>THRESHOLD</span>`;
  _meterEl.appendChild(label);

  container.appendChild(_meterEl);

  // ── Component slider rows ───────────────────────────────────────────────
  for (let i = 0; i < _componentCount; i++) {
    container.appendChild(_buildComponentRow(i));
  }

  // ── Start render ────────────────────────────────────────────────────────
  requestAnimationFrame(() => {
    _canvas.width = _canvas.offsetWidth || 320;
    _rAF = requestAnimationFrame(_drawLoop);
  });
}

/** Apply an assist to the frequency matching puzzle.
 *
 * widen_tolerance (Engineering): shift the threshold marker, flash the meter.
 * relay_frequency (Comms): pre-fill one component's sliders to the exact
 *   target values and highlight the row.
 */
export function applyAssist(assistData) {
  // widen_tolerance assist
  if (typeof assistData.tolerance === 'number') {
    _tolerance = assistData.tolerance;
    if (_meterThreshold) {
      _meterThreshold.style.left = `${(1 - _tolerance) * 100}%`;
    }
    if (_meterEl) {
      _meterEl.classList.add('freq-meter--assist-applied');
      setTimeout(() => _meterEl && _meterEl.classList.remove('freq-meter--assist-applied'), 700);
    }
  }

  // relay_frequency assist (Comms decoded transmission → pre-fill one component)
  if (typeof assistData.component_index === 'number') {
    const idx = assistData.component_index;
    const amp  = assistData.amplitude;
    const freq = assistData.frequency;
    if (_playerComponents[idx] === undefined) return;
    _playerComponents[idx].amplitude  = amp;
    _playerComponents[idx].frequency  = freq;

    // Update the corresponding sliders in the DOM
    if (_container) {
      const rows = _container.querySelectorAll('.freq-component');
      const row  = rows[idx];
      if (row) {
        const sliders = row.querySelectorAll('.freq-slider');
        const vals    = row.querySelectorAll('.freq-component__val');
        // [0]=freq slider, [1]=amp slider
        if (sliders[0]) { sliders[0].value = freq; }
        if (sliders[1]) { sliders[1].value = amp; }
        if (vals[0])    { vals[0].textContent = freq.toFixed(1); }
        if (vals[1])    { vals[1].textContent = amp.toFixed(2); }
        // Highlight the row briefly
        row.style.borderColor = 'var(--system-warning)';
        setTimeout(() => { if (row) row.style.borderColor = ''; }, 2000);
      }
    }
  }
}

/** Return the player's current slider state as a submission payload. */
export function getSubmission() {
  return {
    components: _playerComponents.map(c => ({
      amplitude: c.amplitude,
      frequency: c.frequency,
    })),
  };
}

/** Clean up the render loop and DOM. */
export function destroy() {
  if (_rAF !== null) cancelAnimationFrame(_rAF);
  _rAF = null;
  if (_container) _container.innerHTML = '';
  _canvas = null;
  _ctx = null;
  _meterFill = null;
  _meterThreshold = null;
  _meterEl = null;
  _container = null;
}

// ---------------------------------------------------------------------------
// Waveform maths (mirrored from server)
// ---------------------------------------------------------------------------

const SAMPLE_COUNT = 100;

function _sampleWaveform(components) {
  const out = new Array(SAMPLE_COUNT);
  for (let i = 0; i < SAMPLE_COUNT; i++) {
    let v = 0;
    for (const c of components) {
      v += c.amplitude * Math.sin(2 * Math.PI * c.frequency * i / SAMPLE_COUNT);
    }
    out[i] = v;
  }
  return out;
}

function _relativeRmsError(target, player) {
  const n = target.length;
  if (n === 0) return 1;
  let errSq = 0, tgtSq = 0;
  for (let i = 0; i < n; i++) {
    errSq += (target[i] - player[i]) ** 2;
    tgtSq += target[i] ** 2;
  }
  const tgtRms = Math.sqrt(tgtSq / n) || 1e-6;
  return Math.sqrt(errSq / n) / tgtRms;
}

// ---------------------------------------------------------------------------
// Oscilloscope rendering
// ---------------------------------------------------------------------------

function _drawLoop() {
  _drawScope();
  _updateMeter();
  _rAF = requestAnimationFrame(_drawLoop);
}

function _drawScope() {
  if (!_canvas || !_ctx) return;
  const ctx = _ctx;
  const w = _canvas.width, h = _canvas.height;
  const mid = h / 2;

  // Background.
  ctx.fillStyle = '#020a02';
  ctx.fillRect(0, 0, w, h);

  // Subtle grid.
  ctx.strokeStyle = '#0a280a';
  ctx.lineWidth = 1;
  for (let x = 0; x < w; x += w / 8) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
  for (let y = 0; y <= h; y += h / 4) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }

  // Centre line.
  ctx.strokeStyle = '#0f3a0f';
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(0, mid); ctx.lineTo(w, mid); ctx.stroke();

  const maxAmp = _componentCount * 1.0;
  const scaleY = (h * 0.42) / maxAmp;

  // Helper: draw a waveform from samples.
  function _drawWave(samples, colour) {
    ctx.strokeStyle = colour;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < samples.length; i++) {
      const x = (i / (samples.length - 1)) * w;
      const y = mid - samples[i] * scaleY;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  const targetSamples = _sampleWaveform(_targetComponents);
  const playerSamples = _sampleWaveform(_playerComponents);

  // Draw target (amber/dim) first so player waveform appears on top.
  _drawWave(targetSamples, '#665500');

  // Brighter target highlight.
  ctx.save();
  ctx.strokeStyle = '#ffb000';
  ctx.lineWidth = 1;
  ctx.globalAlpha = 0.5;
  _drawWave(targetSamples, '#ffb000');
  ctx.restore();

  // Player waveform (green).
  _drawWave(playerSamples, '#00ff41');
}

function _updateMeter() {
  if (!_meterFill) return;

  const target = _sampleWaveform(_targetComponents);
  const player = _sampleWaveform(_playerComponents);
  const error  = _relativeRmsError(target, player);

  // Map error → match percentage: 0% error = 100% match.
  const match = Math.max(0, Math.min(100, (1 - error) * 100));

  _meterFill.style.width = `${match}%`;

  // Colour based on whether the player is within tolerance.
  const thresholdMatch = (1 - _tolerance) * 100;
  if (match >= thresholdMatch) {
    _meterFill.className = 'freq-meter__fill freq-meter__fill--match';
  } else if (match >= thresholdMatch * 0.75) {
    _meterFill.className = 'freq-meter__fill freq-meter__fill--warn';
  } else {
    _meterFill.className = 'freq-meter__fill';
  }
}

// ---------------------------------------------------------------------------
// Component row builder
// ---------------------------------------------------------------------------

function _buildComponentRow(idx) {
  const c = _playerComponents[idx];

  const row = document.createElement('div');
  row.className = 'freq-component';

  const header = document.createElement('div');
  header.className = 'freq-component__header text-label';
  header.textContent = `COMPONENT ${idx + 1}`;
  row.appendChild(header);

  const controls = document.createElement('div');
  controls.className = 'freq-component__sliders';

  // Frequency slider.
  const freqLabel = document.createElement('label');
  freqLabel.className = 'text-label';
  freqLabel.textContent = 'FREQ';

  const freqSlider = document.createElement('input');
  freqSlider.type = 'range';
  freqSlider.className = 'freq-slider';
  freqSlider.min = '1.0';
  freqSlider.max = '5.0';
  freqSlider.step = '0.1';
  freqSlider.value = String(c.frequency);

  const freqVal = document.createElement('span');
  freqVal.className = 'freq-component__val text-data';
  freqVal.textContent = c.frequency.toFixed(1);

  freqSlider.addEventListener('input', () => {
    _playerComponents[idx].frequency = parseFloat(freqSlider.value);
    freqVal.textContent = parseFloat(freqSlider.value).toFixed(1);
  });

  // Amplitude slider.
  const ampLabel = document.createElement('label');
  ampLabel.className = 'text-label';
  ampLabel.textContent = 'AMP';

  const ampSlider = document.createElement('input');
  ampSlider.type = 'range';
  ampSlider.className = 'freq-slider';
  ampSlider.min = '0.0';
  ampSlider.max = '1.0';
  ampSlider.step = '0.05';
  ampSlider.value = String(c.amplitude);

  const ampVal = document.createElement('span');
  ampVal.className = 'freq-component__val text-data';
  ampVal.textContent = c.amplitude.toFixed(2);

  ampSlider.addEventListener('input', () => {
    _playerComponents[idx].amplitude = parseFloat(ampSlider.value);
    ampVal.textContent = parseFloat(ampSlider.value).toFixed(2);
  });

  // Layout: [FREQ label] [freq slider] [freq val]  [AMP label] [amp slider] [amp val]
  // 6 cells in 3+3 grid (handled by CSS grid-template-columns: 3rem 1fr 3rem 1fr)
  controls.appendChild(freqLabel);
  controls.appendChild(freqSlider);
  controls.appendChild(freqVal);
  controls.appendChild(ampLabel);
  controls.appendChild(ampSlider);
  controls.appendChild(ampVal);

  row.appendChild(controls);
  return row;
}
