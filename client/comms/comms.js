/**
 * Comms Station — v0.06.4 Full Rewrite.
 *
 * Signal queue management, decode controls, diplomatic response UI,
 * channel management, faction standing display, spectrum analyser,
 * hailing, creature communication, and docking approach prompts.
 *
 * Server messages received:
 *   comms.state              — full comms state (signals, channels, factions, etc.)
 *   comms.npc_response       — NPC reply after a diplomatic response
 *   comms.incoming_transmission — sandbox/mission incoming signal notification
 *   comms.distress_signal    — emergency distress broadcast
 *   comms.distress_assessment — result of distress analysis
 *   puzzle.assist_available  — cross-station assist notification
 *   docking.approach_info    — station approach zone entry
 *   docking.*                — clearance flow messages
 *   ship.alert_changed       — alert level colour swap
 *   ship.hull_hit            — hull hit flash
 *   game.started / game.over — mission lifecycle
 *
 * Server messages sent:
 *   lobby.claim_role          { role, player_name }
 *   comms.tune_frequency      { frequency }
 *   comms.hail                { contact_id, message_type, hail_type, frequency }
 *   comms.decode_signal       { signal_id }
 *   comms.respond             { signal_id, response_id }
 *   comms.route_intel         { signal_id, target_station }
 *   comms.set_channel         { channel, status }
 *   comms.dismiss_signal      { signal_id }
 *   comms.probe               { target_id }
 *   comms.assess_distress     { signal_id }
 *   creature.set_comm_progress { creature_id, progress }
 *   docking.request_clearance  { station_id }
 */
import { connect, on, send } from "/client/shared/connection.js";
import { setStatusDot, showBriefing, showGameOver } from "/client/shared/ui_components.js";
import { initPuzzleRenderer } from "/client/shared/puzzle_renderer.js";
import { initRoleBar } from "/client/shared/role_bar.js";
import { initCrewRoster } from '/client/shared/crew_roster.js';
import { SoundBank } from "/client/shared/audio.js";
import "/client/shared/audio_events.js";
import { wireButtonSounds } from "/client/shared/audio_ui.js";
import { registerHelp, initHelpOverlay } from "/client/shared/help_overlay.js";

registerHelp([
  { selector: '#signal-queue',     text: 'Signal queue — incoming signals sorted by priority. Click a card to view details and respond.', position: 'right' },
  { selector: '#scanner-canvas',   text: 'Frequency scanner — shows faction signal bands on the spectrum.', position: 'left' },
  { selector: '#freq-slider',      text: 'Frequency tuner — slide to lock onto a faction band.', position: 'below' },
  { selector: '#channel-grid',     text: 'Channel management — toggle channels open/monitored/closed to manage bandwidth.', position: 'left' },
  { selector: '#faction-list',     text: 'Faction standings — diplomatic relationships with known factions.', position: 'left' },
  { selector: '#hail-controls',    text: 'Hailing controls — choose a message type and send to a contact.', position: 'left' },
]);

// ── Constants ────────────────────────────────────────────────────────────────

const FACTION_BANDS = {
  imperial:   0.15,
  pirate:     0.08,
  rebel:      0.42,
  civilian:   0.55,
  federation: 0.65,
  alien:      0.71,
  emergency:  0.90,
};

const FACTION_COLOURS = {
  imperial:   "#00aaff",
  pirate:     "#ff6600",
  rebel:      "#ff6600",
  civilian:   "#aaaaaa",
  federation: "#00ccff",
  alien:      "#00ffaa",
  emergency:  "#ff3333",
  unknown:    "#ffff00",
};

const BAND_TOLERANCE = 0.05;

const PRIORITY_COLOURS = {
  critical: "var(--system-critical)",
  high:     "var(--system-warning)",
  medium:   "var(--friendly)",
  low:      "var(--text-dim)",
};

const CHANNEL_CYCLE = ["open", "monitored", "closed"];

// Creature types that support communication
const COMMUNICABLE_TYPES = new Set(['rift_stalker', 'leviathan', 'void_whale']);

const INTEL_ROUTE_TARGETS = [
  "helm", "science", "weapons", "engineering", "captain", "security",
  "electronic_warfare", "operations",
];

// ── State ────────────────────────────────────────────────────────────────────

let activeFrequency = 0.15;
let tunedFaction    = null;
let _selectedSignalId = null;
let _approachStation  = null;
let _creatures        = [];
let _lastState        = null;  // hash guard to prevent DOM thrashing
let _lastStateJson    = "";

// DOM references
let canvas, ctx;
let sliderEl, freqReadoutEl, factionBadgeEl, hailStatusEl;
let hailPanelEl, hailControlsEl;
let signalQueueEl, signalCountEl, bandwidthEl;
let dialoguePanelEl, dialogueSourceEl, dialogueContentEl;
let dialogueActionsEl, responseOptionsEl;
let decodeBarWrapEl, decodeFillEl, decodePctEl;
let channelGridEl, factionListEl;
let creatureSectionEl, creatureCommListEl, creatureCommCountEl;
let assistPanelEl, assistInstructionsEl;
let dockingPromptEl = null;

// ── Initialisation ───────────────────────────────────────────────────────────

function init() {
  canvas              = document.getElementById("scanner-canvas");
  ctx                 = canvas.getContext("2d");
  sliderEl            = document.getElementById("freq-slider");
  freqReadoutEl       = document.getElementById("freq-readout");
  factionBadgeEl      = document.getElementById("faction-badge");
  hailStatusEl        = document.getElementById("hail-status");
  hailPanelEl         = document.getElementById("hail-panel");
  hailControlsEl      = document.getElementById("hail-controls");
  signalQueueEl       = document.getElementById("signal-queue");
  signalCountEl       = document.getElementById("signal-count");
  bandwidthEl         = document.getElementById("bandwidth-indicator");
  dialoguePanelEl     = document.getElementById("dialogue-panel");
  dialogueSourceEl    = document.getElementById("dialogue-source");
  dialogueContentEl   = document.getElementById("dialogue-content");
  dialogueActionsEl   = document.getElementById("dialogue-actions");
  responseOptionsEl   = document.getElementById("response-options");
  decodeBarWrapEl     = document.getElementById("decode-bar-wrap");
  decodeFillEl        = document.getElementById("decode-fill");
  decodePctEl         = document.getElementById("decode-pct");
  channelGridEl       = document.getElementById("channel-grid");
  factionListEl       = document.getElementById("faction-list");
  creatureSectionEl   = document.getElementById("creature-section");
  creatureCommListEl  = document.getElementById("creature-comm-list");
  creatureCommCountEl = document.getElementById("creature-comm-count");
  assistPanelEl       = document.getElementById("assist-panel");
  assistInstructionsEl = document.getElementById("assist-instructions");

  // Canvas sizing
  const wrap = canvas.parentElement;
  const obs = new ResizeObserver(() => resizeCanvas(wrap));
  obs.observe(wrap);
  resizeCanvas(wrap);

  // Frequency slider
  sliderEl.addEventListener("input", () => {
    const freq = parseInt(sliderEl.value, 10) / 1000;
    setFrequency(freq);
    send("comms.tune_frequency", { frequency: freq });
  });

  // Hail buttons
  document.querySelectorAll("[data-hail]").forEach(btn => {
    btn.addEventListener("click", () => {
      const contactId = document.getElementById("contact-id-input").value.trim() || "unknown_vessel";
      send("comms.hail", {
        contact_id: contactId,
        message_type: btn.dataset.hail,
        hail_type: btn.dataset.hail,
      });
    });
  });

  // Dialogue close
  document.getElementById("dialogue-close").addEventListener("click", () => {
    _selectedSignalId = null;
    dialoguePanelEl.style.display = "none";
  });

  // Puzzle overlay
  initPuzzleRenderer(send);

  // Message handlers
  on("comms.state",               handleCommsState);
  on("comms.npc_response",        handleNPCResponse);
  on("comms.incoming_transmission", handleIncomingTransmission);
  on("comms.distress_signal",     handleDistressSignal);
  on("comms.distress_assessment", handleDistressAssessment);
  on("puzzle.assist_available",   handleAssistAvailable);
  on("game.started",   payload => showBriefing(payload.mission_name, payload.briefing_text));
  on("game.over",      payload => { SoundBank.play(payload.result === 'victory' ? 'victory' : 'defeat'); showGameOver(payload.result, payload.stats); });
  on("ship.hull_hit",  () => { SoundBank.play('hull_hit'); document.getElementById("station-container")?.classList.add("hit"); });
  on("ship.state",     () => document.getElementById("station-container")?.classList.remove("hit"));
  on("ship.alert_changed", ({ level }) => setAlertLevel(level));

  // Docking
  on("docking.approach_info",     handleDockingApproachInfo);
  on("docking.clearance_granted", () => _hideDockingPrompt());
  on("docking.clearance_denied",  () => _hideDockingPrompt());

  // Connection
  on("statusChange", status => setStatusDot(document.getElementById("conn-status"), status));

  SoundBank.init();
  wireButtonSounds(SoundBank);
  initHelpOverlay();

  const callsign = sessionStorage.getItem("callsign") || "—";
  document.getElementById("callsign-display").textContent = callsign;

  initRoleBar(send, 'comms');
  initCrewRoster(send);

  on("lobby.welcome", () => {
    const name = sessionStorage.getItem("player_name") || "COMMS";
    send("lobby.claim_role", { role: "comms", player_name: name });
  });
  connect();

  requestAnimationFrame(drawLoop);
}

function resizeCanvas(wrap) {
  const w = wrap.clientWidth  - 8;
  const h = wrap.clientHeight - 8;
  canvas.width  = Math.max(w, 100);
  canvas.height = Math.max(h, 40);
}

// ── Frequency management ─────────────────────────────────────────────────────

function setFrequency(freq) {
  activeFrequency = Math.max(0, Math.min(1, freq));
  sliderEl.value  = Math.round(activeFrequency * 1000);
  freqReadoutEl.textContent = activeFrequency.toFixed(3);

  tunedFaction = null;
  for (const [faction, band] of Object.entries(FACTION_BANDS)) {
    if (Math.abs(activeFrequency - band) <= BAND_TOLERANCE) {
      tunedFaction = faction;
      break;
    }
  }

  if (tunedFaction) {
    factionBadgeEl.textContent = tunedFaction.toUpperCase();
    factionBadgeEl.style.color = FACTION_COLOURS[tunedFaction] || "var(--primary)";
    factionBadgeEl.style.borderColor = FACTION_COLOURS[tunedFaction] || "var(--border-primary)";
    hailStatusEl.textContent = `TUNED — ${tunedFaction.toUpperCase()}`;
    hailPanelEl.style.display    = "none";
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
  // Hash guard to prevent 10Hz DOM thrashing
  const json = JSON.stringify(payload);
  if (json === _lastStateJson) return;
  _lastStateJson = json;
  _lastState = payload;

  // Sync frequency
  if (Math.abs(payload.active_frequency - activeFrequency) > 0.002) {
    setFrequency(payload.active_frequency);
  }

  // Bandwidth indicator
  const bw = payload.bandwidth_quality ?? 1.0;
  const bwPct = Math.round(bw * 100);
  bandwidthEl.textContent = `BW ${bwPct}%`;
  bandwidthEl.className = "bandwidth-indicator" + (
    bwPct < 60 ? " bandwidth-indicator--critical" :
    bwPct < 85 ? " bandwidth-indicator--warn" : ""
  );

  // Signal count
  signalCountEl.textContent = payload.signal_count ?? 0;

  // Render signal queue
  renderSignalQueue(payload.signals || []);

  // Render channels
  renderChannels(payload.channels || []);

  // Render faction standings
  renderFactions(payload.factions || {});

  // Update selected signal dialogue
  if (_selectedSignalId) {
    const sig = (payload.signals || []).find(s => s.id === _selectedSignalId);
    if (sig) renderDialogue(sig, payload.dialogues || {});
  }

  // Creatures
  _creatures = payload.creatures || [];
  renderCreatureComms();
}

function handleNPCResponse(payload) {
  SoundBank.play('incoming_transmission');
}

function handleIncomingTransmission(payload) {
  SoundBank.play('incoming_transmission');
}

function handleDistressSignal(payload) {
  SoundBank.play('incoming_transmission');
}

function handleDistressAssessment(payload) {
  if (!payload) return;
  const risk = payload.risk_level || "unknown";
  const auth = Math.round((payload.authenticity || 0) * 100);
  const factors = (payload.factors || []).join("\n");
  const msg = `DISTRESS ASSESSMENT\nAuthenticity: ${auth}%\nRisk: ${risk.toUpperCase()}\n${factors}`;
  alert(msg);  // Simple modal for assessment results
}

function handleAssistAvailable(payload) {
  if (payload.target_station === "science") {
    assistInstructionsEl.textContent = payload.instructions;
    assistPanelEl.style.display = "";
    setTimeout(() => { assistPanelEl.style.display = "none"; }, 15_000);
  }
}

// ── Signal queue rendering ───────────────────────────────────────────────────

function renderSignalQueue(signals) {
  if (!signals.length) {
    signalQueueEl.innerHTML = '<p class="queue-empty label-sm c-dim">No signals detected.</p>';
    return;
  }

  signalQueueEl.innerHTML = "";

  for (const sig of signals) {
    const card = document.createElement("div");
    card.className = `signal-card signal-card--${sig.priority}`;
    if (sig.id === _selectedSignalId) card.classList.add("signal-card--selected");
    if (sig.decode_progress >= 1.0 && !sig.response_options?.length) card.classList.add("signal-card--decoded");
    if (sig.responded) card.classList.add("signal-card--responded");

    const factionCol = FACTION_COLOURS[sig.faction] || FACTION_COLOURS.unknown;
    const decodePct = Math.round((sig.decode_progress || 0) * 100);

    // Deadline display
    let deadlineHtml = "";
    if (sig.response_deadline != null && sig.response_deadline > 0 && !sig.responded) {
      const secs = Math.round(sig.response_deadline);
      const urgent = secs < 15;
      deadlineHtml = `<span class="signal-card__deadline${urgent ? ' signal-card__deadline--urgent' : ''}">${secs}s</span>`;
    }

    // Preview text
    const preview = sig.decoded_content || sig.raw_content || "";
    const previewTrunc = preview.length > 60 ? preview.slice(0, 57) + "..." : preview;

    card.innerHTML = `
      <div class="signal-card__top">
        <span class="signal-card__source">${escHtml(sig.source_name)}</span>
        <span class="signal-card__type">${sig.signal_type.toUpperCase()}</span>
      </div>
      <div class="signal-card__mid">
        <span class="signal-card__faction" style="color:${factionCol}">${(sig.faction || 'unknown').toUpperCase()}</span>
        ${sig.requires_decode && decodePct < 100 ? `
          <div class="signal-card__decode-bar">
            <div class="signal-card__decode-fill" style="width:${decodePct}%"></div>
          </div>
        ` : ''}
        ${deadlineHtml}
      </div>
      ${previewTrunc ? `<div class="signal-card__preview">${escHtml(previewTrunc)}</div>` : ''}
      <div class="signal-card__btns">
        ${sig.requires_decode && decodePct < 100 ? `<button class="btn btn--sm btn--primary" data-action="decode" data-sid="${sig.id}">DECODE</button>` : ''}
        ${sig.response_options?.length && !sig.responded ? `<button class="btn btn--sm btn--primary" data-action="respond" data-sid="${sig.id}">RESPOND</button>` : ''}
        ${decodePct >= 100 && sig.intel_value ? `<button class="btn btn--sm" data-action="route" data-sid="${sig.id}">ROUTE INTEL</button>` : ''}
        ${sig.signal_type === 'distress' && !sig.responded ? `<button class="btn btn--sm btn--warn" data-action="assess" data-sid="${sig.id}">ASSESS</button>` : ''}
        <button class="btn btn--sm" data-action="dismiss" data-sid="${sig.id}">×</button>
      </div>
    `;

    // Click to select
    card.addEventListener("click", (e) => {
      if (e.target.closest("[data-action]")) return;  // Don't select on button click
      selectSignal(sig);
    });

    signalQueueEl.appendChild(card);
  }

  // Wire action buttons
  signalQueueEl.querySelectorAll("[data-action]").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const action = btn.dataset.action;
      const sid = btn.dataset.sid;
      if (action === "decode") {
        send("comms.decode_signal", { signal_id: sid });
      } else if (action === "respond") {
        const sig = (_lastState?.signals || []).find(s => s.id === sid);
        if (sig) selectSignal(sig);
      } else if (action === "route") {
        showRouteIntelMenu(sid);
      } else if (action === "assess") {
        send("comms.assess_distress", { signal_id: sid });
      } else if (action === "dismiss") {
        send("comms.dismiss_signal", { signal_id: sid });
        if (_selectedSignalId === sid) {
          _selectedSignalId = null;
          dialoguePanelEl.style.display = "none";
        }
      }
    });
  });
}

function selectSignal(sig) {
  _selectedSignalId = sig.id;
  dialoguePanelEl.style.display = "";
  renderDialogue(sig, _lastState?.dialogues || {});
}

function showRouteIntelMenu(signalId) {
  const choice = prompt(
    "Route intel to station:\n" +
    INTEL_ROUTE_TARGETS.map((t, i) => `${i + 1}. ${t}`).join("\n") +
    "\n\nEnter number:"
  );
  const idx = parseInt(choice, 10) - 1;
  if (idx >= 0 && idx < INTEL_ROUTE_TARGETS.length) {
    send("comms.route_intel", { signal_id: signalId, target_station: INTEL_ROUTE_TARGETS[idx] });
  }
}

// ── Dialogue panel ───────────────────────────────────────────────────────────

function renderDialogue(sig, dialogues) {
  dialogueSourceEl.textContent = `${sig.source_name} [${sig.signal_type.toUpperCase()}]`;

  // Decode bar
  if (sig.requires_decode && sig.decode_progress < 1.0) {
    decodeBarWrapEl.style.display = "";
    const pct = Math.round(sig.decode_progress * 100);
    decodeFillEl.style.width = pct + "%";
    decodePctEl.textContent = pct + "%";
    if (sig.decode_progress < 1.0) {
      decodeFillEl.style.background = sig.decoding_active ? "var(--primary)" : "var(--text-dim)";
    }
  } else {
    decodeBarWrapEl.style.display = "none";
  }

  // Dialogue history
  const entries = dialogues[sig.id] || [];
  if (entries.length) {
    dialogueContentEl.innerHTML = entries.map(e => {
      const cls = e.speaker === "you" ? "dialogue-entry--you" : "dialogue-entry--them";
      const label = e.speaker === "you" ? "YOU" : sig.source_name.toUpperCase();
      return `<div class="dialogue-entry ${cls}">
        <div class="dialogue-entry__speaker">${escHtml(label)}</div>
        <div>${escHtml(e.text)}</div>
      </div>`;
    }).join("");
  } else {
    // Show decoded content
    const content = sig.decoded_content || sig.raw_content || "(no content)";
    dialogueContentEl.innerHTML = `<div class="dialogue-entry dialogue-entry--them">
      <div class="dialogue-entry__speaker">${escHtml(sig.source_name.toUpperCase())}</div>
      <div>${escHtml(content)}</div>
    </div>`;
  }

  // Response options
  responseOptionsEl.innerHTML = "";
  if (sig.response_options?.length && !sig.responded) {
    for (const opt of sig.response_options) {
      const btn = document.createElement("button");
      btn.className = "response-btn";
      btn.innerHTML = `
        <div class="response-btn__label">${escHtml(opt.label)}</div>
        <div class="response-btn__desc">${escHtml(opt.description || '')}</div>
        <div class="response-btn__outcome">${escHtml(opt.likely_outcome || '')}</div>
      `;
      btn.addEventListener("click", () => {
        send("comms.respond", { signal_id: sig.id, response_id: opt.id });
      });
      responseOptionsEl.appendChild(btn);
    }
  }

  // Action buttons
  dialogueActionsEl.innerHTML = "";
  if (sig.requires_decode && sig.decode_progress < 1.0) {
    const decBtn = document.createElement("button");
    decBtn.className = "btn btn--sm btn--primary";
    decBtn.textContent = sig.decoding_active ? "DECODING..." : "START DECODE";
    decBtn.disabled = sig.decoding_active;
    decBtn.addEventListener("click", () => {
      send("comms.decode_signal", { signal_id: sig.id });
    });
    dialogueActionsEl.appendChild(decBtn);
  }
  if (sig.decode_progress >= 1.0 && sig.intel_value) {
    const routeBtn = document.createElement("button");
    routeBtn.className = "btn btn--sm";
    routeBtn.textContent = "ROUTE INTEL";
    routeBtn.addEventListener("click", () => showRouteIntelMenu(sig.id));
    dialogueActionsEl.appendChild(routeBtn);
  }
  if (sig.signal_type === "distress" && !sig.responded) {
    const assessBtn = document.createElement("button");
    assessBtn.className = "btn btn--sm btn--warn";
    assessBtn.textContent = "ASSESS";
    assessBtn.addEventListener("click", () => {
      send("comms.assess_distress", { signal_id: sig.id });
    });
    dialogueActionsEl.appendChild(assessBtn);
  }
}

// ── Channel management ───────────────────────────────────────────────────────

function renderChannels(channels) {
  channelGridEl.innerHTML = "";
  for (const ch of channels) {
    const row = document.createElement("div");
    row.className = "channel-row";

    const nameEl = document.createElement("span");
    nameEl.className = "channel-name";
    nameEl.textContent = ch.name;

    const statusBtn = document.createElement("button");
    statusBtn.className = `channel-status-btn channel-status-btn--${ch.status}`;
    statusBtn.textContent = ch.status.toUpperCase();

    // Emergency channel cannot be changed
    if (ch.name === "emergency") {
      statusBtn.classList.add("channel-status-btn--locked");
      statusBtn.title = "Emergency channel always open";
    } else {
      statusBtn.addEventListener("click", () => {
        const currentIdx = CHANNEL_CYCLE.indexOf(ch.status);
        const nextStatus = CHANNEL_CYCLE[(currentIdx + 1) % CHANNEL_CYCLE.length];
        send("comms.set_channel", { channel: ch.name, status: nextStatus });
      });
    }

    const costEl = document.createElement("span");
    costEl.className = "channel-cost";
    costEl.textContent = `${ch.bandwidth_cost}%`;

    row.appendChild(nameEl);
    row.appendChild(statusBtn);
    row.appendChild(costEl);
    channelGridEl.appendChild(row);
  }
}

// ── Faction standings ────────────────────────────────────────────────────────

function renderFactions(factions) {
  factionListEl.innerHTML = "";
  for (const [fid, fs] of Object.entries(factions)) {
    const row = document.createElement("div");
    row.className = "faction-row";

    const nameEl = document.createElement("span");
    nameEl.className = "faction-name";
    nameEl.textContent = fs.name || fid;

    // Standing bar: -100 to +100 → 0% to 100%
    const barEl = document.createElement("div");
    barEl.className = "faction-bar";
    const fillEl = document.createElement("div");
    fillEl.className = "faction-bar__fill";
    const markerEl = document.createElement("div");
    markerEl.className = "faction-bar__marker";

    const standing = fs.standing || 0;
    const normPct = ((standing + 100) / 200) * 100;
    const fillColour = standing > 30 ? "#00aaff"
                     : standing > 0  ? "#00ff41"
                     : standing > -30 ? "#ffaa00"
                     : "#ff4040";

    if (standing >= 0) {
      fillEl.style.left = "50%";
      fillEl.style.width = (normPct - 50) + "%";
    } else {
      fillEl.style.left = normPct + "%";
      fillEl.style.width = (50 - normPct) + "%";
    }
    fillEl.style.background = fillColour;

    barEl.appendChild(fillEl);
    barEl.appendChild(markerEl);

    const dispEl = document.createElement("span");
    const disp = fs.disposition || "neutral";
    dispEl.className = `faction-disposition faction-disposition--${disp}`;
    dispEl.textContent = disp.toUpperCase().replace("_", " ");

    row.appendChild(nameEl);
    row.appendChild(barEl);
    row.appendChild(dispEl);
    factionListEl.appendChild(row);
  }
}

// ── Creature communication ───────────────────────────────────────────────────

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
    const isCalm = ["idle", "dormant", "sedated", "wandering", "fleeing", "redirected"].includes(c.behaviour_state);
    const stateColour = ["attacking", "aggressive", "agitated"].includes(c.behaviour_state)
      ? "var(--system-critical)"
      : isCalm ? "var(--system-healthy)" : "var(--system-warning)";

    const card = document.createElement("div");
    card.className = "creature-card";
    card.innerHTML = `
      <div class="creature-card__header">
        <span style="color:var(--primary)">${typeName}</span>
        <span class="c-dim">${distKm}k</span>
      </div>
      <div>STATE: <span style="color:${stateColour}">${stateLabel}</span></div>
      <div>COMM LINK: <span style="color:var(--primary)">${commPct}%</span></div>
      <div class="creature-card__bar"><div class="creature-card__bar-fill" style="width:${commPct}%"></div></div>
      ${isComplete
        ? '<div style="color:var(--system-healthy)">COMMUNICATION COMPLETE</div>'
        : `<button class="btn btn--sm btn--primary" data-comm-id="${c.id}" style="width:100%"${!isCalm ? ' disabled title="Creature must be calm"' : ''}>
             TRANSMIT SIGNAL
           </button>`
      }
    `;
    creatureCommListEl.appendChild(card);
  }

  creatureCommListEl.querySelectorAll("[data-comm-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const cId = btn.dataset.commId;
      const creature = _creatures.find(cr => cr.id === cId);
      const current = creature ? (creature.communication_progress || 0) : 0;
      const next = Math.min(100, current + 10);
      send("creature.set_comm_progress", { creature_id: cId, progress: next });
    });
  });
}

// ── Docking helpers ──────────────────────────────────────────────────────────

function handleDockingApproachInfo(info) {
  _approachStation = info;
  _renderDockingPrompt();
}

function _renderDockingPrompt() {
  if (!_approachStation) return;

  if (!dockingPromptEl) {
    dockingPromptEl = document.createElement("div");
    dockingPromptEl.id = "docking-prompt";
    dockingPromptEl.style.cssText = "border:1px solid var(--border-primary);padding:8px;margin-bottom:4px;font-size:.7rem";
    const sidebar = document.querySelector(".comms-right");
    if (sidebar) sidebar.prepend(dockingPromptEl);
  }

  const { station_name, distance, docking_range, in_range, speed_ok } = _approachStation;
  const rangeText = `${Math.round(distance)} / ${Math.round(docking_range)} u`;
  const canDock   = in_range && speed_ok;

  dockingPromptEl.innerHTML = `
    <div style="color:var(--primary);letter-spacing:.1em">STATION IN RANGE</div>
    <div>${station_name}</div>
    <div style="color:var(--text-dim)">${rangeText}</div>
    ${!speed_ok ? '<div style="color:var(--system-critical)">REDUCE SPEED &lt;10%</div>' : ''}
    ${canDock
      ? `<button id="request-clearance-btn" style="margin-top:4px;width:100%" class="btn btn--primary btn--sm">REQUEST CLEARANCE</button>`
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

// ── Canvas draw ──────────────────────────────────────────────────────────────

function drawLoop() {
  drawScanner();
  requestAnimationFrame(drawLoop);
}

function drawScanner() {
  const W = canvas.width;
  const H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  ctx.fillStyle = "#0a0f0a";
  ctx.fillRect(0, 0, W, H);

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

    const spikeH = isTuned ? H * 0.55 : H * 0.3;
    ctx.strokeStyle = col;
    ctx.lineWidth = isTuned ? 2 : 1;
    ctx.beginPath();
    ctx.moveTo(bx, axisY);
    ctx.lineTo(bx, axisY - spikeH);
    ctx.stroke();

    ctx.fillStyle = isTuned ? col : col + "88";
    ctx.font = `${isTuned ? "700" : "400"} 11px monospace`;
    ctx.textAlign = "center";
    ctx.fillText(faction.toUpperCase().slice(0, 5), bx, axisY + 12);
  }

  // Tuner line
  const tx = 10 + activeFrequency * (W - 20);
  ctx.strokeStyle = "rgba(0,255,120,0.9)";
  ctx.lineWidth = 1.5;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(tx, 0);
  ctx.lineTo(tx, H);
  ctx.stroke();
  ctx.setLineDash([]);

  // Tuner knob
  ctx.fillStyle = "#00ff78";
  ctx.beginPath();
  ctx.arc(tx, axisY, 4, 0, Math.PI * 2);
  ctx.fill();

  // Noise baseline
  ctx.strokeStyle = "rgba(0,170,80,0.12)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = 10; x < W - 10; x += 3) {
    const noise = (Math.random() - 0.5) * 4;
    if (x === 10) ctx.moveTo(x, axisY + noise);
    else ctx.lineTo(x, axisY + noise);
  }
  ctx.stroke();
}

// ── Utilities ────────────────────────────────────────────────────────────────

function escHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function setAlertLevel(level) {
  const root = document.documentElement;
  const colours = { green: "#00aa50", yellow: "#ffaa00", red: "#ff3333" };
  root.style.setProperty("--primary", colours[level] ?? colours.green);
}

// ── Bootstrap ────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", init);
