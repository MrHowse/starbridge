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

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const JANITOR_NAMES = ['the janitor', 'thejanitor'];

const WELCOME_TEXT = `You are THE JANITOR.

Nobody asked for you. Nobody knows you're here.
But this ship would fall apart without you.

The toilets need fixing. The floors need mopping.
Someone keeps leaving coffee cups on the reactor.

You are the most important person on this ship.
And nobody will ever know.

...

Good luck.`;

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

/** Hash guard — skip full DOM rebuild when state payload is unchanged. */
let _lastStateJson = '';

function handleState(state) {
  const json = JSON.stringify(state);
  if (json === _lastStateJson) return;
  _lastStateJson = json;

  renderTasks(state.tasks || [], state.urgent_tasks || []);
  renderBuffs(state.active_buffs || []);
  renderStickies(state.sticky_notes || []);
  updateStats(state);
}

function handleTaskResult(result) {
  if (!result.ok) return;
  // Brief flash on the task card.
  const card = document.querySelector(`[data-task-id="${result.task_id}"]`);
  if (card) {
    card.style.background = '#d4ecd4';
    setTimeout(() => { card.style.background = ''; }, 800);
  }
}

// ---------------------------------------------------------------------------
// Task rendering
// ---------------------------------------------------------------------------

function renderTasks(tasks, urgents) {
  const listEl = document.getElementById('task-list');
  if (!listEl) return;
  listEl.innerHTML = '';

  // Urgent tasks first.
  if (urgents.length > 0) {
    const section = _createCategory('URGENT');
    for (const u of urgents) {
      const card = document.createElement('div');
      card.className = 'janitor-task janitor-task--urgent';
      card.innerHTML = `<span class="janitor-task__label">${_esc(u.label)}</span>`;
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

  const categoryLabels = {
    plumbing:     'PLUMBING',
    mopping:      'MOPPING',
    restocking:   'RESTOCKING',
    maintenance:  'MAINTENANCE',
    pest_control: 'PEST CONTROL',
    special:      'SPECIAL',
  };

  for (const [cat, catTasks] of Object.entries(groups)) {
    const section = _createCategory(categoryLabels[cat] || cat.toUpperCase());
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

      card.innerHTML =
        `<span class="janitor-task__label">${_esc(task.label)}${countText}</span>` +
        `<span class="janitor-task__status">${cdText}</span>`;

      if (!onCooldown) {
        card.addEventListener('click', () => {
          send('janitor.perform_task', { task_id: task.id });
        });
      }

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
// Stats
// ---------------------------------------------------------------------------

function updateStats(state) {
  const totalEl = document.getElementById('stat-total');
  const buffsEl = document.getElementById('stat-buffs');
  if (totalEl) totalEl.textContent = state.total_tasks_completed || 0;
  if (buffsEl) buffsEl.textContent = (state.active_buffs || []).length;
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
