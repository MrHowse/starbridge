/**
 * Comms Station — client-side logic.
 *
 * Frequency scanner canvas, hailing interface, transmission log,
 * and puzzle overlay wiring for the transmission_decoding puzzle.
 */
import { connect, on, send } from "/client/shared/connection.js";
import { setStatusDot, showBriefing, showGameOver } from "/client/shared/ui_components.js";
import { initPuzzleRenderer } from "/client/shared/puzzle_renderer.js";
import { initRoleBar } from "/client/shared/role_bar.js";
import { SoundBank } from "/client/shared/audio.js";
import "/client/shared/audio_events.js";
import { wireButtonSounds } from "/client/shared/audio_ui.js";
import { registerHelp, initHelpOverlay } from "/client/shared/help_overlay.js";

registerHelp([
  { selector: '#scanner-canvas',    text: 'Frequency scanner — find faction signal bands on the spectrum.', position: 'right' },
  { selector: '#freq-slider',       text: 'Frequency tuner — slide to lock onto a faction\'s band.', position: 'below' },
  { selector: '#hail-controls',     text: 'Hailing controls — choose message type and send to contact.', position: 'left' },
  { selector: '#transmission-log',  text: 'Transmission log — incoming NPC responses appear here.', position: 'left' },
]);

// ── Constants ────────────────────────────────────────────────────────────────

const FACTION_BANDS = {
  imperial:  0.15,
  rebel:     0.42,
  alien:     0.71,
  emergency: 0.90,
};
const FACTION_COLOURS = {
  imperial:  "#00aaff",
  rebel:     "#ff6600",
  alien:     "#00ffaa",
  emergency: "#ff3333",
};
const BAND_TOLERANCE = 0.05;

// ── State ────────────────────────────────────────────────────────────────────

let activeFrequency = 0.15;
let tunedFaction    = null;
let transmissions   = [];
let _approachStation = null;  // current approach-zone station info
let _creatures = [];           // creatures from comms.state

// Creature types that support Comms communication
const COMMUNICABLE_TYPES = new Set(['rift_stalker', 'leviathan', 'void_whale']);

let canvas, ctx;
let sliderEl, freqReadoutEl, factionBadgeEl, hailStatusEl;
let hailPanelEl, hailControlsEl, logEl, assistPanelEl, assistInstructionsEl;
let creatureSectionEl, creatureCommListEl, creatureCommCountEl;
let dockingPromptEl = null;   // dynamically created approach prompt

// ── Initialisation ────────────────────────────────────────────────────────────

function init() {
  canvas  = document.getElementById("scanner-canvas");
  ctx     = canvas.getContext("2d");
  sliderEl            = document.getElementById("freq-slider");
  freqReadoutEl       = document.getElementById("freq-readout");
  factionBadgeEl      = document.getElementById("faction-badge");
  hailStatusEl        = document.getElementById("hail-status");
  hailPanelEl         = document.getElementById("hail-panel");
  hailControlsEl      = document.getElementById("hail-controls");
  logEl               = document.getElementById("transmission-log");
  assistPanelEl       = document.getElementById("assist-panel");
  assistInstructionsEl = document.getElementById("assist-instructions");
  creatureSectionEl   = document.getElementById("creature-section");
  creatureCommListEl  = document.getElementById("creature-comm-list");
  creatureCommCountEl = document.getElementById("creature-comm-count");

  // Size canvas to fill its parent wrap
  const wrap = canvas.parentElement;
  const obs = new ResizeObserver(() => resizeCanvas(wrap));
  obs.observe(wrap);
  resizeCanvas(wrap);

  // Slider input
  sliderEl.addEventListener("input", () => {
    const freq = parseInt(sliderEl.value, 10) / 1000;
    setFrequency(freq);
    send("comms.tune_frequency", { frequency: freq });
  });

  // Hail buttons
  document.querySelectorAll("[data-msg]").forEach(btn => {
    btn.addEventListener("click", () => {
      const contactId = document.getElementById("contact-id-input").value.trim() || "unknown_vessel";
      send("comms.hail", { contact_id: contactId, message_type: btn.dataset.msg });
      addLogEntry(`HAILING ${contactId} [${btn.dataset.msg.toUpperCase()}]...`, "incoming");
    });
  });

  // Puzzle overlay
  initPuzzleRenderer(send);

  // Message handlers
  on("comms.state",        handleCommsState);
  on("comms.npc_response", handleNPCResponse);
  on("puzzle.assist_available", handleAssistAvailable);
  on("game.started",   payload => showBriefing(payload.mission_name, payload.briefing_text));
  on("game.over",      payload => { SoundBank.play(payload.result === 'victory' ? 'victory' : 'defeat'); showGameOver(payload.result, payload.stats); });
  on("ship.hull_hit",  () => { SoundBank.play('hull_hit'); document.getElementById("station-container")?.classList.add("hit"); });
  on("ship.state",     () => document.getElementById("station-container")?.classList.remove("hit"));
  on("ship.alert_changed", ({ level }) => setAlertLevel(level));

  // Docking
  on("docking.approach_info",    handleDockingApproachInfo);
  on("docking.clearance_request", ({ station_name }) => addLogEntry(`Clearance requested from ${station_name}…`, "outgoing"));
  on("docking.clearance_granted", ({ station_name }) => { addLogEntry(`CLEARANCE GRANTED — ${station_name}`, "incoming"); _hideDockingPrompt(); });
  on("docking.clearance_denied",  ({ reason }) => { addLogEntry(`CLEARANCE DENIED: ${reason}`, "incoming"); _hideDockingPrompt(); });
  on("docking.complete",          ({ station_name }) => addLogEntry(`DOCKED AT ${station_name.toUpperCase()}`, "incoming"));
  on("docking.undocked",          () => addLogEntry("Undocking complete — engines online.", "incoming"));

  // Connection
  on("statusChange", status => setStatusDot(document.getElementById("conn-status"), status));

  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();

  const callsign = sessionStorage.getItem("callsign") || "—";
  document.getElementById("callsign-display").textContent = callsign;

  initRoleBar(send, 'comms');

  on("lobby.welcome", () => {
    const name = sessionStorage.getItem("player_name") || "COMMS";
    send("lobby.claim_role", { role: "comms", player_name: name });
  });
  connect();

  requestAnimationFrame(drawLoop);
}

function resizeCanvas(wrap) {
  const w = wrap.clientWidth  - 16;
  const h = wrap.clientHeight - 16;
  canvas.width  = Math.max(w, 100);
  canvas.height = Math.max(h, 60);
}

// ── Frequency management ─────────────────────────────────────────────────────

function setFrequency(freq) {
  activeFrequency = Math.max(0, Math.min(1, freq));
  sliderEl.value  = Math.round(activeFrequency * 1000);
  freqReadoutEl.textContent = activeFrequency.toFixed(3);

  // Detect tuned faction
  tunedFaction = null;
  for (const [faction, band] of Object.entries(FACTION_BANDS)) {
    if (Math.abs(activeFrequency - band) <= BAND_TOLERANCE) {
      tunedFaction = faction;
      break;
    }
  }

  // Update faction badge
  if (tunedFaction) {
    factionBadgeEl.textContent = tunedFaction.toUpperCase();
    factionBadgeEl.style.color = FACTION_COLOURS[tunedFaction] || "var(--primary)";
    factionBadgeEl.style.borderColor = FACTION_COLOURS[tunedFaction] || "var(--border-primary)";
    hailStatusEl.textContent = `TUNED — ${tunedFaction.toUpperCase()}`;
    hailPanelEl.style.display   = "none";
    hailControlsEl.style.display = "";
  } else {
    factionBadgeEl.textContent = "—";
    factionBadgeEl.style.color = "var(--text-dim)";
    factionBadgeEl.style.borderColor = "var(--border-primary)";
    hailStatusEl.textContent = "NO CONTACT";
    hailPanelEl.style.display    = "";
    hailControlsEl.style.display = "none";
  }
}

// ── Message handlers ─────────────────────────────────────────────────────────

function handleCommsState(payload) {
  // Sync if server state differs from our local state (reconnect)
  if (Math.abs(payload.active_frequency - activeFrequency) > 0.002) {
    setFrequency(payload.active_frequency);
  }
  // Update transmission log from server
  if (payload.transmissions && payload.transmissions.length !== transmissions.length) {
    transmissions = payload.transmissions;
    renderLog();
  }
  // Update creature communication panel
  _creatures = payload.creatures || [];
  renderCreatureComms();
}

function handleNPCResponse(payload) {
  SoundBank.play('incoming_transmission');
  addLogEntry(`[${payload.faction.toUpperCase()}]: ${payload.response_text}`, "incoming");
}

function handleAssistAvailable(payload) {
  if (payload.target_station === "science") {
    assistInstructionsEl.textContent = payload.instructions;
    assistPanelEl.style.display = "";
    // Auto-hide after 15s
    setTimeout(() => { assistPanelEl.style.display = "none"; }, 15_000);
  }
}

// ── Transmission log ─────────────────────────────────────────────────────────

function addLogEntry(text, type) {
  transmissions.push({ text, type });
  if (transmissions.length > 10) transmissions.shift();
  renderLog();
}

function renderLog() {
  if (!transmissions.length) {
    logEl.innerHTML = '<p class="log-empty label-sm c-dim">No transmissions received.</p>';
    return;
  }
  logEl.innerHTML = transmissions
    .slice()
    .reverse()
    .map(t => `<div class="log-entry log-entry--${t.type}">${t.text}</div>`)
    .join("");
}

// ── Creature communication ────────────────────────────────────────────────────

function renderCreatureComms() {
  const communicable = _creatures.filter(c => COMMUNICABLE_TYPES.has(c.creature_type));
  creatureCommCountEl.textContent = communicable.length;

  if (communicable.length === 0) {
    creatureSectionEl.style.display = "none";
    return;
  }

  creatureSectionEl.style.display = "";
  creatureCommListEl.innerHTML = "";

  for (const c of communicable) {
    const typeName = c.creature_type.replace(/_/g, " ").toUpperCase();
    const distKm = (c.distance / 1000).toFixed(1);
    const commPct = Math.round(c.communication_progress || 0);
    const stateLabel = (c.behaviour_state || "unknown").toUpperCase();

    const isComplete = commPct >= 100;
    const isSedated = c.behaviour_state === "sedated";
    const isCalm = ["idle", "dormant", "sedated", "wandering", "fleeing", "redirected"].includes(c.behaviour_state);

    const card = document.createElement("div");
    card.className = "log-entry";
    card.style.cssText = "border:1px solid var(--border-primary);padding:6px;margin-bottom:4px;font-size:.7rem";

    const stateColour = ["attacking", "aggressive", "agitated"].includes(c.behaviour_state)
      ? "var(--danger, #ff4040)"
      : isCalm
        ? "var(--success, #00c87a)"
        : "var(--warning, #ffaa00)";

    card.innerHTML = `
      <div style="display:flex;justify-content:space-between">
        <span style="color:var(--primary)">${typeName}</span>
        <span class="c-dim">${distKm}k</span>
      </div>
      <div>STATE: <span style="color:${stateColour}">${stateLabel}</span></div>
      <div>COMM LINK: <span style="color:var(--primary)">${commPct}%</span></div>
      <div style="background:rgba(0,170,80,0.15);height:4px;margin:3px 0">
        <div style="background:var(--primary);height:100%;width:${commPct}%"></div>
      </div>
      ${isComplete
        ? '<div style="color:var(--success)">COMMUNICATION COMPLETE</div>'
        : `<button class="btn btn--sm btn--primary" data-comm-id="${c.id}" style="width:100%;margin-top:3px"${!isCalm ? ' disabled title="Creature must be calm to communicate"' : ''}>
             ${isSedated ? 'COMMUNICATE (SEDATED)' : 'TRANSMIT SIGNAL'}
           </button>`
      }
    `;

    creatureCommListEl.appendChild(card);
  }

  // Wire communicate buttons — each press increments progress by 10
  creatureCommListEl.querySelectorAll("[data-comm-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const cId = btn.dataset.commId;
      const creature = _creatures.find(cr => cr.id === cId);
      const current = creature ? (creature.communication_progress || 0) : 0;
      const next = Math.min(100, current + 10);
      send("creature.set_comm_progress", { creature_id: cId, progress: next });
      addLogEntry(`Transmitting signal to ${cId}… (${next}%)`, "outgoing");
    });
  });
}

// ── Docking helpers ───────────────────────────────────────────────────────────

function handleDockingApproachInfo(info) {
  _approachStation = info;
  _renderDockingPrompt();
}

function _renderDockingPrompt() {
  if (!_approachStation) return;

  // Lazily create the prompt element inside the hail-panel section.
  if (!dockingPromptEl) {
    dockingPromptEl = document.createElement("div");
    dockingPromptEl.id = "docking-prompt";
    dockingPromptEl.style.cssText =
      "border:1px solid var(--border-primary);padding:8px;margin-top:8px;font-size:.7rem";
    const sidebar = document.querySelector(".comms-sidebar");
    if (sidebar) sidebar.prepend(dockingPromptEl);
  }

  const { station_name, distance, docking_range, in_range, speed_ok } = _approachStation;
  const rangeText = `${Math.round(distance)} / ${Math.round(docking_range)} u`;
  const canDock   = in_range && speed_ok;

  dockingPromptEl.innerHTML = `
    <div style="color:var(--primary);letter-spacing:.1em">STATION IN RANGE</div>
    <div>${station_name}</div>
    <div style="color:var(--text-dim)">${rangeText}</div>
    ${!speed_ok ? '<div style="color:var(--danger)">REDUCE SPEED &lt;10%</div>' : ''}
    ${canDock
      ? `<button id="request-clearance-btn" style="margin-top:4px;width:100%" class="btn btn--primary">
           REQUEST CLEARANCE
         </button>`
      : ''}
  `;

  if (canDock) {
    document.getElementById("request-clearance-btn")?.addEventListener("click", () => {
      send("docking.request_clearance", { station_id: _approachStation.station_id });
    });
  }
}

function _hideDockingPrompt() {
  if (dockingPromptEl) {
    dockingPromptEl.innerHTML = "";
    dockingPromptEl.style.display = "none";
  }
  _approachStation = null;
}

// ── Canvas draw ───────────────────────────────────────────────────────────────

function drawLoop() {
  drawScanner();
  requestAnimationFrame(drawLoop);
}

function drawScanner() {
  const W = canvas.width;
  const H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  // Background
  ctx.fillStyle = "#0a0f0a";
  ctx.fillRect(0, 0, W, H);

  // Frequency axis line
  const axisY = H * 0.7;
  ctx.strokeStyle = "rgba(0,170,80,0.3)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(10, axisY);
  ctx.lineTo(W - 10, axisY);
  ctx.stroke();

  // Faction signal blips
  for (const [faction, band] of Object.entries(FACTION_BANDS)) {
    const bx = 10 + band * (W - 20);
    const col = FACTION_COLOURS[faction];
    const isTuned = tunedFaction === faction;

    // Blip spike
    const spikeH = isTuned ? H * 0.55 : H * 0.35;
    const grad = ctx.createLinearGradient(bx, axisY - spikeH, bx, axisY);
    grad.addColorStop(0, col + "ff");
    grad.addColorStop(1, col + "00");
    ctx.strokeStyle = col;
    ctx.lineWidth   = isTuned ? 2 : 1;
    ctx.beginPath();
    ctx.moveTo(bx, axisY);
    ctx.lineTo(bx, axisY - spikeH);
    ctx.stroke();

    // Label
    ctx.fillStyle = isTuned ? col : col + "99";
    ctx.font       = `${isTuned ? "700" : "400"} 9px monospace`;
    ctx.textAlign  = "center";
    ctx.fillText(faction.toUpperCase(), bx, axisY + 14);
    ctx.fillText(band.toFixed(2), bx, axisY + 24);
  }

  // Tuner line
  const tx = 10 + activeFrequency * (W - 20);
  ctx.strokeStyle = "rgba(0,255,120,0.9)";
  ctx.lineWidth   = 1.5;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(tx, 0);
  ctx.lineTo(tx, H);
  ctx.stroke();
  ctx.setLineDash([]);

  // Tuner knob
  ctx.fillStyle = "#00ff78";
  ctx.beginPath();
  ctx.arc(tx, axisY, 5, 0, Math.PI * 2);
  ctx.fill();

  // Noise baseline (static effect)
  ctx.strokeStyle = "rgba(0,170,80,0.15)";
  ctx.lineWidth   = 1;
  ctx.beginPath();
  for (let x = 10; x < W - 10; x += 3) {
    const noise = (Math.random() - 0.5) * 6;
    if (x === 10) ctx.moveTo(x, axisY + noise);
    else ctx.lineTo(x, axisY + noise);
  }
  ctx.stroke();
}

// ── Bootstrap ────────────────────────────────────────────────────────────────

function setAlertLevel(level) {
  const root = document.documentElement;
  const colours = { green: "#00aa50", yellow: "#ffaa00", red: "#ff3333" };
  root.style.setProperty("--primary", colours[level] ?? colours.green);
}

document.addEventListener("DOMContentLoaded", init);
