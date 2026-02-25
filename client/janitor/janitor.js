/**
 * Starbridge — Janitor Station (Secret)
 *
 * Easter egg station unlocked by setting player name to "The Janitor".
 * Completely different visual aesthetic (clipboard/corkboard vs sci-fi wireframe).
 * Maps mundane janitorial tasks to real game mechanics.
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import { setStatusDot } from '../shared/ui_components.js';
import { initRoleBar } from '../shared/role_bar.js';
import { SoundBank, getCtx } from '../shared/audio.js';
import '../shared/audio_ambient.js';
import '../shared/audio_events.js';
import { wireButtonSounds } from '../shared/audio_ui.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const JANITOR_NAMES = ['the janitor', 'thejanitor'];

const WELCOME_TEXT = `Welcome to Janitorial Supplies.

You are the Janitor.

Your mop is your sceptre. Your plunger is your sword.
Your supply closet is your throne room.

The crew thinks you're nobody. They're wrong.

Everything on this ship flows through the pipes.
And you control the pipes.

Good luck. The toilets on Deck 3 are backed up again.`;

// ---------------------------------------------------------------------------
// Auth check
// ---------------------------------------------------------------------------

const playerName = (sessionStorage.getItem('player_name') || '').trim().toLowerCase();
const isJanitor  = JANITOR_NAMES.includes(playerName);

const lockedScreen = document.getElementById('locked-screen');
const mainScreen   = document.getElementById('janitor-main');

if (!isJanitor) {
  // Show locked door, do not connect.
  lockedScreen.style.display = '';
  mainScreen.style.display   = 'none';
} else {
  // Hide locked door, show station.
  lockedScreen.style.display = 'none';
  mainScreen.style.display   = '';
  init();
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

function init() {
  const statusDotEl   = document.querySelector('[data-status-dot]');
  const statusLabelEl = document.querySelector('[data-status-label]');

  // Audio setup — standard controls + background MP3 loop.
  SoundBank.init();
  wireButtonSounds(SoundBank);
  _startBackgroundAudio();

  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    if (statusLabelEl) statusLabelEl.textContent = status.toUpperCase();
  });

  on('game.started', () => {
    showWelcomeCrawl();
  });

  on('janitor.state', handleState);
  on('janitor.task_result', handleTaskResult);

  initRoleBar(send, 'janitor');
  connect();

  // Auto-reclaim role.
  const myRole = sessionStorage.getItem('my_role');
  if (myRole === 'janitor') {
    const name = sessionStorage.getItem('player_name') || '';
    setTimeout(() => {
      send('lobby.claim_role', { role: 'janitor', player_name: name });
    }, 500);
  }
}

// ---------------------------------------------------------------------------
// Background audio — fluorescent light hum (MP3 loop via Web Audio API)
// ---------------------------------------------------------------------------

function _startBackgroundAudio() {
  const ctx = getCtx();
  const ambientGain = SoundBank.getCategoryGain('ambient');
  if (!ambientGain) return;

  fetch('/assets/fluro.mp3')
    .then(res => res.arrayBuffer())
    .then(buf => ctx.decodeAudioData(buf))
    .then(audioBuffer => {
      const src = ctx.createBufferSource();
      src.buffer = audioBuffer;
      src.loop = true;
      src.connect(ambientGain);
      src.start(0);
    })
    .catch(() => { /* asset missing or decode failure — silent fallback */ });
}

// ---------------------------------------------------------------------------
// Welcome crawl
// ---------------------------------------------------------------------------

let _crawlShown = false;

function showWelcomeCrawl() {
  if (_crawlShown) return;
  _crawlShown = true;

  const overlay = document.getElementById('welcome-crawl');
  const textEl  = document.getElementById('crawl-text');
  if (!overlay || !textEl) return;

  overlay.style.display = 'flex';
  textEl.textContent = WELCOME_TEXT;

  // Dismiss on click.
  overlay.addEventListener('click', () => {
    overlay.style.display = 'none';
  });

  // Auto-dismiss after 10 seconds.
  setTimeout(() => { overlay.style.display = 'none'; }, 10000);
}

// ---------------------------------------------------------------------------
// State handler
// ---------------------------------------------------------------------------

/** Hash guards — skip sections whose data hasn't changed. */
let _lastBuffsJson   = '';
let _lastStickyJson  = '';
let _lastCondJson    = '';

function handleState(state) {
  updateTasks(state.tasks || [], state.urgent_tasks || []);

  const buffsJson = JSON.stringify(state.active_buffs || []);
  if (buffsJson !== _lastBuffsJson) {
    _lastBuffsJson = buffsJson;
    renderBuffs(state.active_buffs || []);
  }

  const stickyJson = JSON.stringify(state.sticky_notes || []);
  if (stickyJson !== _lastStickyJson) {
    _lastStickyJson = stickyJson;
    renderStickies(state.sticky_notes || []);
  }

  const condJson = JSON.stringify(state.deck_conditions || []);
  if (condJson !== _lastCondJson) {
    _lastCondJson = condJson;
    renderDeckConditions(state.deck_conditions || []);
  }

  updateSupplyStatus(state);
  updateStats(state);
}

/** Show task result message as a brief toast. */
function handleTaskResult(result) {
  if (!result.ok) return;
  // Brief flash on the task card.
  const card = document.querySelector(`[data-task-id="${result.task_id}"]`);
  if (card) {
    card.style.background = '#d4ecd4';
    setTimeout(() => { card.style.background = ''; }, 1200);
  }
  // Show result message as toast.
  if (result.message) _showToast(result.message);
}

function _showToast(msg) {
  let toast = document.getElementById('janitor-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'janitor-toast';
    toast.className = 'janitor-toast';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add('janitor-toast--visible');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    toast.classList.remove('janitor-toast--visible');
  }, 3000);
}

// ---------------------------------------------------------------------------
// Task rendering — build DOM once, update in-place thereafter
// ---------------------------------------------------------------------------

const CATEGORY_LABELS = {
  plumbing:     'PLUMBING',
  mopping:      'MOPPING',
  restocking:   'RESTOCKING',
  maintenance:  'MAINTENANCE TUNNELS',
  pest_control: 'PEST CONTROL',
  special:      'SPECIAL',
};

/** Whether the task list DOM has been built at least once. */
let _taskListBuilt = false;

/**
 * Build the task list DOM on first call; update in-place on subsequent calls.
 * This avoids full DOM rebuilds that kill hover/click states.
 */
function updateTasks(tasks, urgents) {
  const listEl = document.getElementById('task-list');
  if (!listEl) return;

  if (!_taskListBuilt) {
    _buildTaskList(listEl, tasks, urgents);
    _taskListBuilt = true;
    return;
  }

  // --- In-place update of existing cards ---

  // Update urgent section.
  const urgentSection = listEl.querySelector('[data-category="urgent"]');
  if (urgents.length > 0 && !urgentSection) {
    // Urgents appeared — rebuild.
    _taskListBuilt = false;
    _buildTaskList(listEl, tasks, urgents);
    _taskListBuilt = true;
    return;
  }
  if (urgents.length === 0 && urgentSection) {
    urgentSection.remove();
  }

  // Update each task card in-place.
  for (const task of tasks) {
    const card = listEl.querySelector(`[data-task-id="${task.id}"]`);
    if (!card) continue;

    const onCooldown = !task.ready;
    const cdText = onCooldown ? `${Math.ceil(task.cooldown_remaining)}s` : 'READY';
    const statusEl = card.querySelector('.janitor-task__status');
    if (statusEl && statusEl.textContent !== cdText) {
      statusEl.textContent = cdText;
    }

    // Update count badge.
    const countEl = card.querySelector('.janitor-task__count');
    if (task.times_performed > 0) {
      const countText = `x${task.times_performed}`;
      if (countEl) {
        if (countEl.textContent !== countText) countEl.textContent = countText;
      } else {
        const badge = document.createElement('span');
        badge.className = 'janitor-task__count';
        badge.textContent = countText;
        card.querySelector('.janitor-task__label').appendChild(badge);
      }
    }

    // Toggle cooldown class.
    card.classList.toggle('janitor-task--cooldown', onCooldown);
  }
}

/** Full DOM build — called once on first state, or when structure changes. */
function _buildTaskList(listEl, tasks, urgents) {
  listEl.innerHTML = '';

  // Urgent tasks first.
  if (urgents.length > 0) {
    const section = _createCategory('URGENT');
    section.dataset.category = 'urgent';
    for (const u of urgents) {
      const card = document.createElement('div');
      card.className = 'janitor-task janitor-task--urgent';
      card.innerHTML =
        `<span class="janitor-task__label">${_esc(u.label)}</span>` +
        (u.flavour ? `<span class="janitor-task__flavour">${_esc(u.flavour)}</span>` : '');
      section.appendChild(card);
    }
    listEl.appendChild(section);
  }

  // Group by category.
  const groups = {};
  for (const task of tasks) {
    const cat = task.category || 'other';
    if (!groups[cat]) groups[cat] = [];
    groups[cat].push(task);
  }

  for (const [cat, catTasks] of Object.entries(groups)) {
    const section = _createCategory(CATEGORY_LABELS[cat] || cat.toUpperCase());
    for (const task of catTasks) {
      const onCooldown = !task.ready;
      const card = document.createElement('div');
      card.className = `janitor-task${onCooldown ? ' janitor-task--cooldown' : ''}`;
      card.dataset.taskId = task.id;

      const cdText = onCooldown
        ? `${Math.ceil(task.cooldown_remaining)}s`
        : 'READY';
      const countText = task.times_performed > 0
        ? `<span class="janitor-task__count">x${task.times_performed}</span>`
        : '';
      const flavourHtml = task.flavour
        ? `<span class="janitor-task__flavour">${_esc(task.flavour)}</span>`
        : '';

      card.innerHTML =
        `<div class="janitor-task__top">` +
          `<span class="janitor-task__label">${_esc(task.label)}${countText}</span>` +
          `<span class="janitor-task__status">${cdText}</span>` +
        `</div>` +
        flavourHtml;

      // Click handler — always attached; checks cooldown at click time.
      card.addEventListener('click', () => {
        if (card.classList.contains('janitor-task--cooldown')) return;
        send('janitor.perform_task', { task_id: task.id });
      });

      section.appendChild(card);
    }
    listEl.appendChild(section);
  }
}

function _createCategory(label) {
  const div = document.createElement('div');
  div.className = 'janitor-task-category';
  div.innerHTML = `<div class="janitor-task-category__label">${_esc(label)}</div>`;
  return div;
}

// ---------------------------------------------------------------------------
// Deck condition rendering
// ---------------------------------------------------------------------------

const CONDITION_ICONS = {
  tidy:      '\u2713',  // ✓
  disaster:  '\u2715',  // ✕
  biohazard: '\u2623',  // ☣
  fire:      '\u{1F525}', // 🔥
};

function renderDeckConditions(conditions) {
  const el = document.getElementById('deck-conditions');
  if (!el) return;

  if (conditions.length === 0) {
    el.innerHTML = '<p class="text-dim">No deck data.</p>';
    return;
  }

  el.innerHTML = '';
  for (const c of conditions) {
    const row = document.createElement('div');
    row.className = `janitor-condition janitor-condition--${c.icon}`;
    const icon = CONDITION_ICONS[c.icon] || '?';
    row.innerHTML =
      `<span class="janitor-condition__deck">Deck ${_esc(c.deck)}:</span>` +
      `<span class="janitor-condition__status">${_esc(c.status)} ${icon}</span>`;
    el.appendChild(row);
  }
}

// ---------------------------------------------------------------------------
// Supply status rendering
// ---------------------------------------------------------------------------

function updateSupplyStatus(state) {
  const el = document.getElementById('supply-status');
  if (!el) return;

  const stats = state.stats || {};
  const tp = stats.toilets_fixed || 0;
  const coffee = stats.coffee_restocked || 0;
  const buffs = (state.active_buffs || []).length;

  // Supplies deplete as you use them, regenerate slowly.
  // This is cosmetic — just a fun display.
  const tpLevel = Math.max(0, 100 - tp * 12);
  const coffeeLevel = Math.max(0, 100 - coffee * 20);

  el.innerHTML =
    `<div class="janitor-supply">Coffee: <strong>${coffeeLevel > 50 ? 'OK' : coffeeLevel > 20 ? 'Running low' : 'EMPTY!'}</strong></div>` +
    `<div class="janitor-supply">TP: <strong>${tpLevel > 50 ? 'Stocked' : tpLevel > 20 ? 'LOW' : 'CRITICAL LOW'}</strong></div>` +
    `<div class="janitor-supply">Active repairs: <strong>${buffs}</strong></div>`;
}

// ---------------------------------------------------------------------------
// Buff rendering
// ---------------------------------------------------------------------------

function renderBuffs(buffs) {
  const el = document.getElementById('buff-list');
  if (!el) return;

  if (buffs.length === 0) {
    el.innerHTML = '<p class="text-dim">No active effects.</p>';
    return;
  }

  el.innerHTML = '';
  for (const buff of buffs) {
    const row = document.createElement('div');
    row.className = 'janitor-buff';
    row.innerHTML =
      `<span class="janitor-buff__system">${_esc(buff.system)}</span>` +
      `<span>+${Math.round(buff.amount * 100)}%</span>` +
      `<span class="janitor-buff__timer">${Math.ceil(buff.remaining)}s</span>`;
    el.appendChild(row);
  }
}

// ---------------------------------------------------------------------------
// Sticky note rendering
// ---------------------------------------------------------------------------

function renderStickies(notes) {
  const el = document.getElementById('sticky-list');
  if (!el) return;

  if (notes.length === 0) {
    el.innerHTML = '<p class="text-dim">No messages.</p>';
    return;
  }

  el.innerHTML = '';
  for (const note of notes) {
    const sticky = document.createElement('div');
    sticky.className = 'janitor-sticky';
    sticky.innerHTML =
      `${_esc(note.text)}` +
      `<button class="janitor-sticky__dismiss" title="Dismiss">&times;</button>`;
    sticky.querySelector('.janitor-sticky__dismiss').addEventListener('click', () => {
      send('janitor.dismiss_sticky', { sticky_id: note.id });
    });
    el.appendChild(sticky);
  }
}

// ---------------------------------------------------------------------------
// Flavoured stats bar
// ---------------------------------------------------------------------------

function updateStats(state) {
  const stats = state.stats || {};
  const toiletsEl = document.getElementById('stat-toilets');
  const floorsEl  = document.getElementById('stat-floors');
  const coffeeEl  = document.getElementById('stat-coffee');
  const ratsEl    = document.getElementById('stat-rats');
  if (toiletsEl) toiletsEl.textContent = stats.toilets_fixed || 0;
  if (floorsEl)  floorsEl.textContent  = stats.floors_mopped || 0;
  if (coffeeEl)  coffeeEl.textContent  = stats.coffee_restocked || 0;
  if (ratsEl)    ratsEl.textContent    = stats.rat_traps_set || 0;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
