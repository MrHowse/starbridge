/**
 * Mission Debrief — standalone page.
 *
 * Reads `starbridge_debrief` from localStorage (saved by showGameOver /
 * captain's handleGameOver), then renders:
 *   - Header meta (result, duration, hull)
 *   - Awards earned
 *   - Key moments timeline
 *   - Captain's log entries
 *   - Per-station stats table
 *   - Captain's Replay: animated ship-path playback on a minimap canvas
 */

// ---------------------------------------------------------------------------
// Load data
// ---------------------------------------------------------------------------

const WORLD_SIZE = 100_000;

let _data = null;
try {
  const raw = localStorage.getItem('starbridge_debrief');
  if (raw) _data = JSON.parse(raw);
} catch (_) { /* parse error */ }

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const titleEl      = document.getElementById('debrief-title');
const resultBadge  = document.getElementById('debrief-result-badge');
const durationEl   = document.getElementById('debrief-duration');
const hullEl       = document.getElementById('debrief-hull');
const noDataEl     = document.getElementById('debrief-no-data');
const bodyEl       = document.getElementById('debrief-body');

const awardsList   = document.getElementById('awards-list');
const momentsList  = document.getElementById('moments-list');
const captainList  = document.getElementById('captain-log-list');
const statsTbody   = document.getElementById('stats-tbody');

const replayCanvas = document.getElementById('replay-canvas');
const replayCtx    = replayCanvas.getContext('2d');
const playBtn      = document.getElementById('replay-play-btn');
const scrubEl      = document.getElementById('replay-scrub');
const replayTimeEl = document.getElementById('replay-time');
const speedEl      = document.getElementById('replay-speed');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtDuration(s) {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = String(Math.round(s % 60)).padStart(2, '0');
  return `${m}:${sec}`;
}

function fmtTs(s) {
  const m = Math.floor(s / 60);
  const sec = String(Math.floor(s % 60)).padStart(2, '0');
  return `T+${m}:${sec}`;
}

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function topEvent(eventsObj) {
  if (!eventsObj || typeof eventsObj !== 'object') return '—';
  const entries = Object.entries(eventsObj);
  if (!entries.length) return '—';
  entries.sort((a, b) => b[1] - a[1]);
  const [key, count] = entries[0];
  return `${key.replace(/_/g, ' ')} ×${count}`;
}

// Role display labels
const ROLE_LABELS = {
  helm:                'HELM',
  weapons:             'WEAPONS',
  engineering:         'ENGINEERING',
  science:             'SCIENCE',
  medical:             'MEDICAL',
  security:            'SECURITY',
  comms:               'COMMS',
  flight_ops:          'FLIGHT OPS',
  electronic_warfare:  'EW',
  operations:          'OPERATIONS',
  captain:             'CAPTAIN',
};

// ---------------------------------------------------------------------------
// Render header
// ---------------------------------------------------------------------------

function renderHeader(data) {
  document.title = 'STARBRIDGE — ' + (data.result === 'victory' ? 'MISSION COMPLETE' : 'SHIP DESTROYED');
  titleEl.textContent = data.result === 'victory' ? 'MISSION DEBRIEF — VICTORY' : 'MISSION DEBRIEF — DEFEAT';
  resultBadge.textContent  = data.result === 'victory' ? '[ VICTORY ]' : '[ DEFEAT ]';
  resultBadge.style.color  = data.result === 'victory' ? '#00ff88' : '#ff4040';
  durationEl.textContent   = `DURATION: ${fmtDuration(data.duration_s)}`;
  hullEl.textContent       = data.hull_remaining != null
    ? `HULL: ${Math.round(data.hull_remaining)}%` : 'HULL: —';
  if (data.difficulty) {
    const diffEl = document.createElement('span');
    diffEl.className = 'debrief__difficulty';
    diffEl.textContent = `DIFFICULTY: ${data.difficulty.toUpperCase()}`;
    diffEl.style.cssText = 'margin-left:1.5em;opacity:0.7;';
    durationEl.parentNode.insertBefore(diffEl, durationEl.nextSibling);
  }
}

// ---------------------------------------------------------------------------
// Render awards
// ---------------------------------------------------------------------------

function renderAwards(awards) {
  if (!awards || !awards.length) return;
  awardsList.innerHTML = '';
  for (const { role, award, description } of awards) {
    const div = document.createElement('div');
    div.className = 'award-item';
    div.innerHTML = `
      <span class="award-role">${esc(ROLE_LABELS[role] || role)}</span>
      <span class="award-name">★ ${esc(award)}</span>
      <span class="award-desc">${esc(description)}</span>
    `;
    awardsList.appendChild(div);
  }
}

// ---------------------------------------------------------------------------
// Render key moments
// ---------------------------------------------------------------------------

function renderMoments(moments) {
  if (!moments || !moments.length) return;
  momentsList.innerHTML = '';
  for (const { ts, text } of moments) {
    const div = document.createElement('div');
    div.className = 'moment-item';
    div.innerHTML = `<span class="moment-ts">${fmtTs(ts)}</span><span>${esc(text)}</span>`;
    momentsList.appendChild(div);
  }
}

// ---------------------------------------------------------------------------
// Render captain's log
// ---------------------------------------------------------------------------

function renderCaptainLog(log) {
  if (!log || !log.length) return;
  captainList.innerHTML = '';
  for (const entry of log) {
    const div = document.createElement('div');
    div.className = 'log-entry';
    const ts = entry.timestamp != null ? `<span class="log-entry-ts">T+${fmtDuration(entry.timestamp)}</span>` : '';
    div.innerHTML = `${ts}<span>${esc(entry.text || entry)}</span>`;
    captainList.appendChild(div);
  }
}

// ---------------------------------------------------------------------------
// Render stats table
// ---------------------------------------------------------------------------

function renderStats(perStation) {
  if (!perStation || typeof perStation !== 'object') return;
  statsTbody.innerHTML = '';
  const rows = Object.entries(perStation).sort((a, b) => b[1].total - a[1].total);
  for (const [role, data] of rows) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="stat-role">${esc(ROLE_LABELS[role] || role)}</td>
      <td class="stat-count">${data.total}</td>
      <td class="stat-top">${esc(topEvent(data.events))}</td>
    `;
    statsTbody.appendChild(tr);
  }
}

// ---------------------------------------------------------------------------
// Render dynamic missions
// ---------------------------------------------------------------------------

const missionsPanel = document.getElementById('missions-debrief-panel');
const missionsList  = document.getElementById('missions-debrief-list');

function renderMissions(dm) {
  if (!dm || dm.missions_offered === 0) return;
  missionsPanel.style.display = '';
  missionsList.innerHTML = '';

  // Summary row
  const summary = document.createElement('div');
  summary.className = 'debrief-missions-summary';
  summary.innerHTML = `
    <div class="debrief-stat-row">
      <span class="text-label">OFFERED</span><span class="text-body">${dm.missions_offered}</span>
    </div>
    <div class="debrief-stat-row">
      <span class="text-label">ACCEPTED</span><span class="text-body">${dm.missions_accepted}</span>
    </div>
    <div class="debrief-stat-row">
      <span class="text-label">COMPLETED</span><span class="text-body debrief-val--good">${dm.missions_completed}</span>
    </div>
    <div class="debrief-stat-row">
      <span class="text-label">FAILED</span><span class="text-body debrief-val--bad">${dm.missions_failed}</span>
    </div>
    <div class="debrief-stat-row">
      <span class="text-label">DECLINED / EXPIRED</span><span class="text-body">${dm.missions_declined + dm.missions_expired}</span>
    </div>
    <div class="debrief-stat-row">
      <span class="text-label">OBJECTIVES</span><span class="text-body">${dm.objectives_completed} / ${dm.objectives_total}</span>
    </div>
  `;
  missionsList.appendChild(summary);

  // Mission details
  if (dm.mission_details && dm.mission_details.length) {
    for (const m of dm.mission_details) {
      const completed = dm.completion_details?.find(c => c.mission_id === m.id);
      const failed    = dm.failure_details?.find(f => f.mission_id === m.id);
      const status = completed ? 'COMPLETED' : failed ? 'FAILED' : 'OFFERED';
      const cls    = completed ? 'debrief-val--good' : failed ? 'debrief-val--bad' : '';

      const row = document.createElement('div');
      row.className = 'debrief-mission-detail';
      row.innerHTML = `
        <span class="debrief-mission-type">${esc(m.mission_type?.toUpperCase() || '—')}</span>
        <span class="debrief-mission-title">${esc(m.title || '—')}</span>
        <span class="debrief-mission-status ${cls}">${status}</span>
      `;
      missionsList.appendChild(row);
    }
  }

  // Total rewards
  const rew = dm.total_rewards;
  if (rew && (rew.crew > 0 || rew.reputation > 0 || Object.keys(rew.supplies || {}).length)) {
    const rewDiv = document.createElement('div');
    rewDiv.className = 'debrief-rewards';
    let html = '<span class="text-label">TOTAL REWARDS:</span>';
    if (rew.crew > 0) html += ` <span class="text-body">+${rew.crew} crew</span>`;
    if (rew.reputation > 0) html += ` <span class="text-body">+${rew.reputation} rep</span>`;
    for (const [item, qty] of Object.entries(rew.supplies || {})) {
      html += ` <span class="text-body">+${qty} ${esc(item)}</span>`;
    }
    rewDiv.innerHTML = html;
    missionsList.appendChild(rewDiv);
  }
}

// ---------------------------------------------------------------------------
// Render comms performance
// ---------------------------------------------------------------------------

const commsPanel = document.getElementById('comms-debrief-panel');
const commsList  = document.getElementById('comms-debrief-list');

function renderCommsPerformance(cp) {
  if (!cp || (cp.signals_decoded === 0 && cp.hails_sent === 0 && cp.intel_routed === 0)) return;
  commsPanel.style.display = '';
  commsList.innerHTML = '';

  const stats = document.createElement('div');
  stats.className = 'debrief-comms-stats';
  stats.innerHTML = `
    <div class="debrief-stat-row">
      <span class="text-label">SIGNALS DECODED</span><span class="text-body">${cp.signals_decoded}</span>
    </div>
    <div class="debrief-stat-row">
      <span class="text-label">AVG DECODE TIME</span><span class="text-body">${cp.avg_decode_time > 0 ? cp.avg_decode_time + 's' : '—'}</span>
    </div>
    <div class="debrief-stat-row">
      <span class="text-label">INTEL ROUTED</span><span class="text-body">${cp.intel_routed}</span>
    </div>
    <div class="debrief-stat-row">
      <span class="text-label">HAILS SENT</span><span class="text-body">${cp.hails_sent}</span>
    </div>
    <div class="debrief-stat-row">
      <span class="text-label">DIPLOMATIC RESPONSES</span><span class="text-body">${cp.diplomatic_responses}</span>
    </div>
  `;
  commsList.appendChild(stats);

  // Intel destinations
  if (cp.intel_destinations && Object.keys(cp.intel_destinations).length) {
    const destDiv = document.createElement('div');
    destDiv.className = 'debrief-intel-destinations';
    let html = '<span class="text-label">INTEL DESTINATIONS:</span>';
    for (const [dest, count] of Object.entries(cp.intel_destinations)) {
      html += ` <span class="text-body">${esc(dest)} ×${count}</span>`;
    }
    destDiv.innerHTML = html;
    commsList.appendChild(destDiv);
  }

  // Net faction standings
  if (cp.net_standings && Object.keys(cp.net_standings).length) {
    const standDiv = document.createElement('div');
    standDiv.className = 'debrief-standings';
    standDiv.innerHTML = '<span class="text-label">NET STANDING CHANGES:</span>';
    for (const [faction, amount] of Object.entries(cp.net_standings)) {
      const sign = amount >= 0 ? '+' : '';
      const cls  = amount >= 0 ? 'debrief-val--good' : 'debrief-val--bad';
      const item = document.createElement('span');
      item.className = `text-body ${cls}`;
      item.textContent = ` ${esc(faction)}: ${sign}${amount}`;
      standDiv.appendChild(item);
    }
    commsList.appendChild(standDiv);
  }
}

// ---------------------------------------------------------------------------
// Captain's Replay
// ---------------------------------------------------------------------------

const PADDING = 24;  // canvas padding in px

let _timeline   = [];
let _moments    = [];
let _replayIdx  = 0;   // current frame index
let _playing    = false;
let _raf        = null;
let _lastFrame  = null;

function worldToCanvas(wx, wy) {
  const w = replayCanvas.width  - PADDING * 2;
  const h = replayCanvas.height - PADDING * 2;
  const cx = PADDING + (wx / WORLD_SIZE) * w;
  const cy = PADDING + (wy / WORLD_SIZE) * h;
  return [cx, cy];
}

function drawReplayFrame(idx) {
  const cw = replayCanvas.width;
  const ch = replayCanvas.height;
  replayCtx.clearRect(0, 0, cw, ch);

  // Background grid lines
  replayCtx.strokeStyle = '#1a2333';
  replayCtx.lineWidth = 1;
  for (let g = 0; g <= 4; g++) {
    const x = PADDING + (g / 4) * (cw - PADDING * 2);
    const y = PADDING + (g / 4) * (ch - PADDING * 2);
    replayCtx.beginPath();
    replayCtx.moveTo(x, PADDING); replayCtx.lineTo(x, ch - PADDING);
    replayCtx.stroke();
    replayCtx.beginPath();
    replayCtx.moveTo(PADDING, y); replayCtx.lineTo(cw - PADDING, y);
    replayCtx.stroke();
  }

  if (!_timeline.length) return;

  // Draw path up to idx
  const end = Math.min(idx, _timeline.length - 1);
  if (end >= 1) {
    replayCtx.beginPath();
    const [x0, y0] = worldToCanvas(_timeline[0].x, _timeline[0].y);
    replayCtx.moveTo(x0, y0);
    for (let i = 1; i <= end; i++) {
      const [xi, yi] = worldToCanvas(_timeline[i].x, _timeline[i].y);
      replayCtx.lineTo(xi, yi);
    }
    replayCtx.strokeStyle = 'rgba(0,212,255,0.5)';
    replayCtx.lineWidth = 1.5;
    replayCtx.stroke();
  }

  // Key moment markers (only those with ts <= current ts)
  const currentTs = _timeline[end]?.ts ?? 0;
  for (const { ts, text } of _moments) {
    if (ts > currentTs) continue;
    // Find nearest timeline point at or before this ts.
    const pt = _timeline.slice(0, end + 1).findLast(t => t.ts <= ts) ?? _timeline[0];
    if (!pt) continue;
    const [mx, my] = worldToCanvas(pt.x, pt.y);
    replayCtx.beginPath();
    replayCtx.arc(mx, my, 5, 0, Math.PI * 2);
    replayCtx.fillStyle = '#ffd700';
    replayCtx.fill();
  }

  // Current ship position
  const pt = _timeline[end];
  if (pt) {
    const [sx, sy] = worldToCanvas(pt.x, pt.y);
    replayCtx.beginPath();
    replayCtx.arc(sx, sy, 5, 0, Math.PI * 2);
    replayCtx.fillStyle = '#00d4ff';
    replayCtx.fill();
    replayCtx.strokeStyle = '#ffffff';
    replayCtx.lineWidth = 1;
    replayCtx.stroke();
  }
}

function updateReplayScrub(idx) {
  scrubEl.value = idx;
  const ts = _timeline[idx]?.ts ?? 0;
  replayTimeEl.textContent = fmtTs(ts);
  drawReplayFrame(idx);
}

function replayStep(now) {
  if (!_playing) return;
  const speed = parseFloat(speedEl.value) || 4;
  const dt = _lastFrame != null ? (now - _lastFrame) / 1000 : 0;
  _lastFrame = now;

  // Each timeline entry spans ~10 seconds of game time (100 ticks at 10 Hz).
  // We advance frames proportional to speed.
  _replayIdx = Math.min(
    _timeline.length - 1,
    _replayIdx + dt * speed * 0.1,  // 0.1 frame/s real → adjusted by speed
  );
  const frame = Math.floor(_replayIdx);
  updateReplayScrub(frame);

  if (frame >= _timeline.length - 1) {
    _playing = false;
    playBtn.textContent = 'PLAY';
    _replayIdx = _timeline.length - 1;
    return;
  }
  _raf = requestAnimationFrame(replayStep);
}

function initReplay(timeline, moments) {
  _timeline = timeline || [];
  _moments  = moments  || [];

  if (!_timeline.length) {
    replayCanvas.style.display = 'none';
    document.querySelector('.replay-controls').style.display = 'none';
    document.querySelector('.replay-legend').style.display = 'none';
    return;
  }

  scrubEl.max   = _timeline.length - 1;
  scrubEl.value = 0;
  _replayIdx    = 0;
  drawReplayFrame(0);

  playBtn.addEventListener('click', () => {
    if (_playing) {
      _playing = false;
      playBtn.textContent = 'PLAY';
      if (_raf) cancelAnimationFrame(_raf);
    } else {
      if (_replayIdx >= _timeline.length - 1) _replayIdx = 0;
      _playing    = true;
      _lastFrame  = null;
      playBtn.textContent = 'PAUSE';
      _raf = requestAnimationFrame(replayStep);
    }
  });

  scrubEl.addEventListener('input', () => {
    _replayIdx = parseInt(scrubEl.value, 10);
    updateReplayScrub(_replayIdx);
  });
}

// ---------------------------------------------------------------------------
// Main entry
// ---------------------------------------------------------------------------

if (!_data || !_data.debrief) {
  noDataEl.style.display = '';
} else {
  bodyEl.style.display = '';
  renderHeader(_data);
  renderAwards(_data.debrief.awards);
  renderMoments(_data.debrief.key_moments);
  renderCaptainLog(_data.captain_log);
  renderMissions(_data.debrief.dynamic_missions);
  renderCommsPerformance(_data.debrief.comms_performance);
  renderStats(_data.debrief.per_station_stats);
  initReplay(_data.debrief.timeline, _data.debrief.key_moments);
}
