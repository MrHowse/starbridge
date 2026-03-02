# STARBRIDGE v0.08 — STATION REWORK & CROSS-STATION INTEGRATION
## Complete Specification & Audit Checklist

**Version:** 1.0
**Date:** March 2026
**Author:** Peter Howse / Claude
**Status:** Specification
**Depends on:** v0.07 (ship class differentiation, Quartermaster)

---

## OVERVIEW

v0.08 has three goals:

1. **Replace Tactical with Operations (Ops)** — the crew's analyst and coordinator. Ops processes data from every station and produces actionable intelligence that makes the whole crew measurably more effective.

2. **Replace Damage Control with Hazard Control** — the ship's environmental crisis manager. Hazard Control owns atmosphere, fire, radiation, structural integrity, and emergency systems. Engineering fixes components; Hazard Control keeps the spaces safe for crew to work in.

3. **Deepen cross-station integration** — every station's actions should visibly affect other stations. Information flows between stations. Decisions on one station create consequences on others. The crew should feel like a connected organism, not 12 people playing separate games.

**Design Principle:** No station operates in isolation. Every action has a ripple. The game rewards communication and punishes silos.

---

# PART A: OPERATIONS STATION

## A.1 STATION IDENTITY

[ ] A.1.1 Rename "Tactical" to "Operations" throughout the codebase: server, client, lobby, role registry, all references.

[ ] A.1.2 Station callsign: "Ops"

[ ] A.1.3 Station description (lobby): "Analyses threats, coordinates crew actions, and manages mission execution. The crew's brain — turning raw data into tactical advantage."

[ ] A.1.4 Ops replaces Tactical in the station list. Same position in the role bar. Tactical no longer exists as a selectable role.

[ ] A.1.5 Ops is available on all ship classes. On a cruiser, Ops gets enhanced tools (see A.4 — Flag Bridge integration from v0.07 section 2.4 transfers to Ops).

## A.2 ENEMY ANALYSIS SYSTEM

The core mechanic. Ops takes raw scan data from Science and produces tactical intelligence that gives concrete, measurable bonuses to other stations.

### A.2.1 Battle Assessment

[ ] A.2.1.1 Ops can run a "Battle Assessment" on any contact that Science has scanned. The contact must have been scanned (at least basic scan complete) — Ops cannot assess unscanned contacts. If Ops tries to assess an unscanned contact, the UI shows: "Insufficient sensor data — request scan from Science."

[ ] A.2.1.2 Battle Assessment takes 15 seconds per contact. During assessment, a progress bar shows on the Ops UI. Ops can cancel and restart on a different contact. Only one assessment runs at a time.

[ ] A.2.1.3 Assessment speed is modified by: Science scan quality (+25% speed if detailed scan, -25% if only basic scan), EW jamming of that contact (+15% speed if EW is jamming the target — disrupting their ECM makes analysis easier), sensor system health (scales with Science station crew factor and sensor component health).

[ ] A.2.1.4 Assessment results persist until the contact is destroyed or moves out of sensor range for more than 60 seconds. If the contact returns to sensor range within 60 seconds, the assessment is still valid.

### A.2.2 Shield Harmonics Analysis

[ ] A.2.2.1 On assessment completion, Ops receives shield harmonics data showing the shield strength per facing (fore, aft, port, starboard) of the enemy contact.

[ ] A.2.2.2 Ops can designate the weakest facing as "VULNERABLE FACING" on the contact. This information is pushed to:
- **Weapons**: Shows as a directional indicator on the target lock display — an arrow pointing to the weak facing. If Weapons fires when the ship's attack vector is within 30° of the vulnerable facing, beam damage to shields is increased by 25%.
- **Helm**: Shows as an approach vector recommendation on the navigation display — a green arc around the target showing the optimal engagement angle.
- **Captain**: Shows on the tactical overview as a colour-coded shield diagram on the contact.

[ ] A.2.2.3 Shield harmonics update every 30 seconds while the contact is assessed and in sensor range. If enemy shields rebalance, Ops sees the change and can update the vulnerable facing designation.

### A.2.3 System Vulnerability Scan

[ ] A.2.3.1 Assessment reveals the health percentage of enemy subsystems: engines, weapons, shields, sensors, and propulsion.

[ ] A.2.3.2 Ops can designate one enemy subsystem as "PRIORITY SUBSYSTEM." This is pushed to:
- **Weapons**: Beam and torpedo hits have a 20% increased chance of damaging the designated subsystem specifically (normally damage is distributed randomly across enemy systems).
- **Flight Ops**: Combat drones targeting an assessed enemy with a priority subsystem marked focus their attacks on that subsystem.

[ ] A.2.3.3 Only one subsystem can be designated per contact at a time. Changing the designation has a 10-second cooldown.

### A.2.4 Behaviour Prediction

[ ] A.2.4.1 Based on the assessed contact's heading, speed, acceleration pattern, and combat behaviour observed over the last 30 seconds, Ops can generate a 30-second movement prediction.

[ ] A.2.4.2 Prediction is shown as a dashed line extending from the contact's current position with a ghost marker at the predicted 30-second position. This appears on:
- **Helm**: Navigation display — helps Helm pre-position for engagement or evasion.
- **Weapons**: Targeting display — if the contact is within 10% of predicted position when fired upon, Weapons gets +10% accuracy bonus ("predictable target").
- **Ops map**: Always visible to Ops as part of the assessment overlay.
- **Captain**: Tactical overview.

[ ] A.2.4.3 Prediction accuracy depends on contact behaviour. Contacts travelling in a straight line are highly predictable. Contacts performing evasive manoeuvres are poorly predictable. Ops sees a "PREDICTION CONFIDENCE" percentage (high/medium/low) so they know how reliable the prediction is.

[ ] A.2.4.4 Prediction refreshes every 10 seconds while active. Ops can toggle prediction on/off per assessed contact.

### A.2.5 Threat Assessment

[ ] A.2.5.1 Ops assigns threat levels to contacts: LOW (green), MEDIUM (amber), HIGH (red), CRITICAL (flashing red). This is a manual assignment based on Ops' judgement — the game provides data, Ops makes the call.

[ ] A.2.5.2 Threat level effects:
- **LOW**: Contact marker is green on all station maps. No special behaviour.
- **MEDIUM**: Contact marker is amber on all station maps. Appears in Captain's priority list.
- **HIGH**: Contact marker is red on all station maps. Flashes on Weapons target list. Audio alert on Captain station: single chime.
- **CRITICAL**: Contact marker flashes red on ALL station maps with pulsing border. Audio alert on ALL stations: two-tone alarm. Contact is auto-added to top of Captain's priority target list. Weapons and Flight Ops see "CRITICAL THREAT" banner.

[ ] A.2.5.3 Ops can change threat level at any time. Changes propagate to all stations within 1 tick.

[ ] A.2.5.4 Threat level persists on contact until changed by Ops or contact is destroyed/leaves sensor range.

## A.3 COORDINATION BONUSES

Ops creates measurable bonuses by actively coordinating between stations. These are not automatic — Ops must designate, manage, and time them.

### A.3.1 Weapons-Helm Sync

[ ] A.3.1.1 Ops designates a contact and an approach bearing (click on a contact, then click a direction on the map to set the vector).

[ ] A.3.1.2 The sync request appears on Helm as a vector line on the navigation display and on Weapons as a targeting arc on the weapons display.

[ ] A.3.1.3 If Helm maintains heading within 15° of the designated vector AND the ship is within beam range of the target, a "SYNC ACTIVE" indicator lights up on Weapons, Helm, and Ops simultaneously. While SYNC ACTIVE:
- Weapons beam accuracy: +15%
- Weapons beam damage: +10%
- Duration: persists as long as Helm holds the vector (±15°)

[ ] A.3.1.4 If Helm deviates beyond 15°, SYNC breaks. Ops must re-designate. There is a 15-second cooldown before a new sync can be established on the same contact.

[ ] A.3.1.5 Only one Weapons-Helm Sync can be active at a time.

### A.3.2 Sensor Focus

[ ] A.3.2.1 Ops designates a circular region on the map (click centre, drag radius, 5000-20000 unit radius). The region is labelled "SENSOR FOCUS ZONE."

[ ] A.3.2.2 Effects within the focus zone:
- **Science**: Scan speed +25% for contacts inside the zone. Passive detection range +15% within the zone.
- **EW**: Jam effectiveness +20% against contacts inside the zone.
- **Comms**: Signal decode speed +15% for signals originating from within the zone.
- **Flight Ops**: Drones within the zone get +15% sensor range.

[ ] A.3.2.3 The focus zone is visible on Science, EW, Comms, and Flight Ops maps as a dashed circle with "SENSOR FOCUS" label.

[ ] A.3.2.4 Only one focus zone active at a time. Ops can move it by dragging. Dissolves automatically if Ops switches to a different activity for more than 60 seconds (Ops must actively maintain focus).

### A.3.3 Damage Coordination

[ ] A.3.3.1 When the ship takes damage, Ops can run a "Damage Assessment" (5-second process). This produces a prioritised damage summary that is pushed to:
- **Engineering**: A sorted list of damaged systems with health percentages, colour-coded by priority (CRITICAL red, HIGH amber, MODERATE yellow, LOW green). Replaces Engineering's default unsorted damage alerts for 30 seconds. Engineering sees: "OPS PRIORITY: 1. Engines 45% 2. Shields 60% 3. Sensors 85%"
- **Hazard Control**: A sorted list of environmental hazards by severity. "OPS PRIORITY: 1. Fire Deck 3 (intensity 4) 2. Breach Deck 5 (depressurising) 3. Radiation Deck 2 (moderate)"
- **Medical**: Casualty prediction — "Estimated 2-3 casualties from current conditions on Decks 3 and 5. Recommend pre-staging triage."

[ ] A.3.3.2 Damage Assessment has a 45-second cooldown. Ops cannot spam it every tick.

[ ] A.3.3.3 Stations can dismiss the Ops priority overlay by clicking [DISMISS] if they prefer their own prioritisation.

### A.3.4 Evasion Alert

[ ] A.3.4.1 When Ops detects incoming torpedoes (from sensor data), Ops can issue an "EVASION ALERT" with a recommended evasion direction (click a direction on the map).

[ ] A.3.4.2 Helm sees the evasion recommendation as a flashing directional arrow on their display with "OPS: EVADE →" label.

[ ] A.3.4.3 If Helm follows the recommendation (turns toward the recommended direction within 5 seconds), incoming torpedo accuracy is reduced by 15% (the ship is moving optimally relative to the torpedo approach vector).

[ ] A.3.4.4 Evasion Alert has a 20-second cooldown. The bonus only applies if Helm actually follows the recommendation.

## A.4 MISSION MANAGEMENT

[ ] A.4.1 Active missions from Comms / Quartermaster service contracts are tracked on the Ops station with objective-by-objective progress.

[ ] A.4.2 Ops sees: mission title, each objective with status (PENDING / IN PROGRESS / COMPLETE / FAILED), estimated time remaining, and which station is primarily responsible for each objective ("Navigate to waypoint → Helm", "Scan target → Science", "Neutralise hostiles → Weapons").

[ ] A.4.3 Ops can mark objectives as "IN PROGRESS" when the crew begins work. This appears on the Captain's display as progress tracking.

[ ] A.4.4 Ops can issue "STATION ADVISORY" messages to any specific station: a short text that appears as a notification banner on the receiving station's display. Example: Ops sends to Helm: "Hold position at waypoint for 30 seconds — Science scanning." Helm sees a banner: "OPS ADVISORY: Hold position at waypoint for 30 seconds — Science scanning."

[ ] A.4.5 Station Advisory messages persist for 15 seconds on the receiving station, then fade. Maximum 1 advisory per station at a time (new replaces old). Ops types the message (max 80 characters) and selects the target station from a dropdown.

## A.5 OPERATIONS UI

### A.5.1 Layout

[ ] A.5.1.1 Three-panel layout.

[ ] A.5.1.2 **Centre: Tactical Map** — large map showing all contacts with Ops-specific overlays (threat levels, assessment indicators, prediction lines, vulnerable facing arcs, sync vectors, sensor focus zones, mission waypoints). Click interactions: click contact for assessment, click map for sync vector / focus zone / evasion direction. Range selector matching other station maps.

[ ] A.5.1.3 **Left: Analysis Panel** — currently selected contact's assessment data. Shield harmonics diagram (4-facing display with fill levels), system health bars, behaviour prediction confidence, threat level selector buttons. Below: active coordination bonuses with timers and status (SYNC ACTIVE, FOCUS ACTIVE, etc.).

[ ] A.5.1.4 **Right: Information Feed & Mission Tracker** — scrolling feed of key events from all stations (filtered to significant events only — not every tick, just state changes and alerts). Below: active mission tracker with objectives and progress. Below: Station Advisory composer (text input + station dropdown + [SEND]).

[ ] A.5.1.5 **Bottom bar**: Active coordination bonus summary, assessment queue, ship status quick-view (hull, shields, speed).

### A.5.2 Information Feed Events

The right panel feed shows filtered highlights from all stations. Ops sees more than any other station about what's happening across the ship.

[ ] A.5.2.1 Events that appear in the Ops feed (with station source tag):
- [SCIENCE] New contact detected / contact scanned / contact lost
- [WEAPONS] Target engaged / torpedo fired / target destroyed
- [HELM] Course change > 30° / speed change > 25% / full stop / collision warning
- [ENGINEERING] System below 50% health / reactor alert / overclock warning / repair complete on critical system
- [HAZARD] Fire started / breach detected / radiation alert / deck evacuated
- [MEDICAL] Mass casualty event (3+ simultaneous) / critical patient / patient death
- [SECURITY] Boarding detected / intruders on deck / marine engagement / intruders repelled
- [COMMS] New signal decoded / faction standing change / hail received from unknown
- [EW] Enemy jamming detected / intrusion attempt detected / countermeasures activated
- [FLIGHT OPS] Drone launched / drone lost / drone contact detected / bingo fuel warning
- [QUARTERMASTER] Resource critical (<10%) / trade completed / allocation denied

[ ] A.5.2.2 Each feed item is timestamped and colour-coded by severity (white = info, amber = warning, red = critical).

[ ] A.5.2.3 Feed maximum 50 items, oldest scroll off the top. New items appear at the bottom with a brief highlight animation.

### A.5.3 Audio

[ ] A.5.3.1 Assessment complete: data chime
[ ] A.5.3.2 Sync activated: positive connection tone
[ ] A.5.3.3 Sync broken: disconnect tone
[ ] A.5.3.4 Threat level changed to CRITICAL: alarm
[ ] A.5.3.5 Incoming torpedo detected: urgent warning
[ ] A.5.3.6 Mission objective completed: achievement chime
[ ] A.5.3.7 Station advisory sent: sent confirmation
[ ] A.5.3.8 Feed item critical severity: subtle alert ping

---

# PART B: HAZARD CONTROL STATION

## B.1 STATION IDENTITY

[ ] B.1.1 Rename "Damage Control" to "Hazard Control" throughout the codebase: server, client, lobby, role registry, all references.

[ ] B.1.2 Station callsign: "HazCon"

[ ] B.1.3 Station description (lobby): "Manages fires, atmosphere, radiation, and structural integrity. Keeps the ship's environment survivable so the crew can do their jobs."

[ ] B.1.4 Hazard Control replaces Damage Control in the station list. Same position in the role bar. Damage Control no longer exists as a selectable role.

[ ] B.1.5 Hazard Control is available on all ship classes.

## B.2 FIRE SYSTEM

### B.2.1 Fire Model

[ ] B.2.1.1 Fires occur in specific rooms on the interior map. Each fire has: room_id, intensity (1-5), spread_timer (seconds until it spreads to an adjacent room), started_tick.

[ ] B.2.1.2 Fire intensity effects:
- **Intensity 1** (Smouldering): Crew effectiveness on deck -5%. No spread risk for 60 seconds. Cosmetic smoke.
- **Intensity 2** (Small fire): Crew effectiveness -15%. Spreads to adjacent room in 90 seconds if unsuppressed.
- **Intensity 3** (Moderate fire): Crew effectiveness -30%. Spreads in 60 seconds. Crew take minor injury (1 HP/30s) if in room.
- **Intensity 4** (Major fire): Crew effectiveness -60%. Spreads in 30 seconds. Crew take moderate injury (3 HP/30s). Equipment in room takes 2% damage per 10 seconds.
- **Intensity 5** (Inferno): Crew effectiveness -100% (deck unusable). Spreads in 15 seconds. Crew take serious injury (5 HP/30s) — must evacuate. Equipment takes 5% damage per 10 seconds. Adjacent rooms take 1% equipment damage per 30 seconds from heat.

[ ] B.2.1.3 Fires increase in intensity over time if unsuppressed: +1 intensity every 45 seconds. A smouldering fire becomes an inferno in 3 minutes if ignored.

[ ] B.2.1.4 Fire causes are:
- Combat damage: torpedo/beam hit on a deck → 40% chance of intensity 2 fire in the hit room
- System overload: Engineering overclock damage → 15% chance of intensity 1 fire in that system's room
- Reactor damage: reactor component failure → 25% chance of intensity 3 fire on engineering deck
- Boarding: boarder explosives/sabotage → intensity 2-3 fire
- Cascade: fire spreading from adjacent room starts at (source_intensity - 1)

### B.2.2 Fire Suppression

[ ] B.2.2.1 **Localised suppression**: Target a single room. Reduces fire intensity by 2 per use. Takes 5 seconds. Costs 1 suppressant unit. Can be used multiple times on the same fire.

[ ] B.2.2.2 **Deck-wide suppression**: Targets an entire deck. Reduces all fires on that deck by 1 intensity. Takes 15 seconds to activate. Costs 3 suppressant units. Effective but expensive.

[ ] B.2.2.3 **Ventilation cutoff**: Seal a room's air supply. Fire loses 1 intensity every 20 seconds (oxygen starvation). Costs no suppressant. BUT: crew in the sealed room start taking oxygen deprivation damage after 30 seconds (must evacuate first). Room atmosphere goes to 0% O2 and must be restored after fire is out.

[ ] B.2.2.4 **Manual fire team**: Hazard Control can dispatch a fire team (if available crew on that deck) to fight the fire manually. Reduces intensity by 1 every 20 seconds. Team takes injury risk (10% chance of minor injury per 20-second cycle). Doesn't cost suppressant.

[ ] B.2.2.5 Fire suppressant is a finite resource. Starting supply per ship class:
- Scout: 8 units
- Corvette: 12 units
- Frigate: 15 units
- Cruiser: 20 units
- Battleship: 30 units
- Carrier: 25 units
- Medical ship: 12 units

[ ] B.2.2.6 Suppressant can be resupplied by the Quartermaster at vendors.

[ ] B.2.2.7 When suppressant reaches 0, Hazard Control can only use ventilation cutoff and manual fire teams. UI shows suppressant count prominently.

### B.2.3 Fire Cross-Station Effects

[ ] B.2.3.1 Fire in a room affects the station whose equipment is in that room. Fire in the weapons bay → Weapons systems on that deck take equipment damage (see B.2.1.2 intensity 4-5). Fire in engineering → reactor and power systems take damage. Fire in the medical bay → Medical cannot treat patients in that bay until fire is suppressed.

[ ] B.2.3.2 Fire on the flight deck suspends ALL drone launch and recovery operations (existing v0.06.5 mechanic). Hazard Control must suppress the flight deck fire before Flight Ops can resume.

[ ] B.2.3.3 Fire triggers automatic crew movement: crew in rooms at intensity 3+ move to adjacent safe rooms. This changes crew_factor per deck dynamically. Engineering, Security, and Medical see crew redistribution in real time.

[ ] B.2.3.4 Smoke from fires reduces internal sensor accuracy for Security. Rooms with intensity 2+ fires show as "OBSCURED" on Security's interior map — boarder detection is reduced by 50% in those rooms.

## B.3 ATMOSPHERE SYSTEM

### B.3.1 Atmospheric Model

[ ] B.3.1.1 Each room on the interior map has atmospheric readings: oxygen_percent (0-100), pressure_kpa (0-101.3), temperature_c (normal: 22°, danger above 45° or below 5°), contamination_level (0-100, types: smoke, coolant, radiation, chemical).

[ ] B.3.1.2 Normal atmosphere: O2 = 21%, pressure = 101.3 kPa, temp = 22°C, contamination = 0. These are baseline and maintained by life support automatically.

[ ] B.3.1.3 Life support is a ship system managed by Engineering (power allocation). When life support has full power, it restores room atmospheres at a rate of 2% O2 per 10 seconds and 5 kPa per 10 seconds. Reduced power → reduced restore rate proportionally.

[ ] B.3.1.4 Atmospheric changes per hazard:
- **Hull breach**: Pressure drops at 10 kPa/s (total vacuum in ~10 seconds for a major breach, 30 seconds for a minor one). O2 drops proportionally. Temperature drops toward space ambient (-270°C at 1°/s outside, but internal heating resists — effective cooling is 2°C/s once breach is sealed).
- **Fire**: Temperature rises 3°C per fire intensity per 30 seconds. O2 drops 1% per fire intensity per 30 seconds (fire consuming oxygen). Smoke contamination rises 5% per fire intensity per 30 seconds.
- **Coolant leak**: Coolant contamination rises 10% per 30 seconds. Crew in coolant-contaminated rooms (>30%) take chemical damage.
- **Radiation**: Radiation contamination rises based on source severity. See B.4.

### B.3.2 Hull Breach Management

[ ] B.3.2.1 Hull breaches are caused by: torpedo hits (70% chance of breach on hit deck), heavy beam damage (30% chance), structural collapse, boarding entry.

[ ] B.3.2.2 Breach severity: MINOR (1m² — slow decompression, 30s to vacuum) or MAJOR (3m² — rapid decompression, 10s to vacuum).

[ ] B.3.2.3 Hazard Control response options:
- **Emergency force field**: Instant seal, holds for 120 seconds, then fails. Costs no resources but is temporary. Buys time for Engineering to patch.
- **Emergency bulkhead seal**: Seal the room permanently. Takes 5 seconds. Room is isolated — no crew entry/exit, no atmosphere exchange. The breach is contained but the room is unusable until Engineering patches the hull AND Hazard Control unseals the bulkhead.
- **Directed evacuation**: Order crew out of the breached room/deck. Crew move to adjacent safe areas within 10 seconds. Must be done BEFORE sealing or crew are trapped.

[ ] B.3.2.4 Breach status is visible to Engineering as a repair task: "Hull breach Deck 4, Room 3 — patch required." Engineering dispatches a repair team to physically patch the breach. Until patched, the force field timer is the only thing between that room and vacuum.

[ ] B.3.2.5 If a room reaches 0 kPa (full vacuum): all crew in the room take 10 HP/s damage (lethal in seconds). Equipment takes 3% damage per second. The room is flagged "VACUUM" on all interior maps. Crew cannot enter. Engineering repair teams require EVA equipment to work in vacuum rooms (repair takes 2x longer).

### B.3.3 Ventilation Management

[ ] B.3.3.1 Hazard Control manages the ventilation network between rooms and decks. Ventilation can be: OPEN (normal air flow), FILTERED (air flows but contaminants are scrubbed — slow, 5% contamination reduction per 30s), or SEALED (no air flow between connected rooms).

[ ] B.3.3.2 Ventilation controls are shown on the interior map as connections between rooms. Hazard Control clicks a connection to cycle OPEN → FILTERED → SEALED.

[ ] B.3.3.3 Ventilation decisions create trade-offs:
- Sealing a deck stops fire spread and contamination spread, but also stops fresh air flow — O2 depletes over time if life support can't reach the sealed area.
- Opening ventilation to clear smoke from Deck 3 is good, UNLESS Deck 4 has a radiation leak — opening the connection between Deck 3 and 4 spreads radiation into Deck 3.
- Filtered mode is safe but slow — contamination is scrubbed but at a fraction of the speed of just venting to an open area.

[ ] B.3.3.4 Emergency vent to space: Hazard Control can open an external vent on any deck, blowing the atmosphere (and all contaminants) into space. This is the nuclear option — the deck is instantly clear of smoke, coolant, and radiation, but also clear of air. Crew must evacuate first. Atmosphere must be restored afterwards (life support takes 60-90 seconds to re-pressurise a vented deck).

### B.3.4 Atmosphere Cross-Station Effects

[ ] B.3.4.1 Low O2 (<15%) on a deck: crew effectiveness on that deck reduced by 40%. Crew take 1 HP per 30 seconds. Engineering repair teams on that deck work at 50% speed.

[ ] B.3.4.2 High temperature (>40°C) on a deck: crew effectiveness reduced by 20%. Equipment cooling fails — systems on that deck degrade 1% per 30 seconds.

[ ] B.3.4.3 High contamination (>50%) on a deck: crew take damage based on contamination type (smoke: minor, coolant: moderate, radiation: serious). Medical sees contamination-type injuries arriving from affected decks.

[ ] B.3.4.4 Atmosphere status per deck is visible to Medical as a summary: "Deck 3: HAZARDOUS (smoke, low O2). Expect: respiratory injuries." Medical can pre-stage treatment based on this information.

## B.4 RADIATION SYSTEM

### B.4.1 Radiation Sources

[ ] B.4.1.1 Reactor damage: when the reactor takes damage below 60% health, it leaks radiation onto the engineering deck. Leak rate proportional to damage severity. At 30% reactor health: serious radiation leak affecting engineering deck and adjacent decks.

[ ] B.4.1.2 Nuclear torpedo impact: the hit room and all rooms on the same deck become irradiated (contamination 80+). Adjacent decks get moderate contamination (40+).

[ ] B.4.1.3 Damaged shield emitters: shields below 25% can leak ambient radiation through the weakened barrier. Low-level contamination (10-20%) on outer decks.

### B.4.2 Radiation Zones

[ ] B.4.2.1 Radiation contamination levels shown on the interior map as colour overlays:
- 0-10%: GREEN — safe, no effect
- 11-30%: AMBER — low risk, crew take 0.5 HP per 60 seconds. Long exposure (>3 minutes) causes radiation sickness (Medical injury).
- 31-60%: ORANGE — moderate risk, crew take 1 HP per 30 seconds. Exposure >60 seconds causes radiation sickness.
- 61-100%: RED — high risk, crew take 3 HP per 10 seconds. Immediate radiation sickness on any exposure.

### B.4.3 Radiation Containment

[ ] B.4.3.1 **Seal the area**: Close ventilation to prevent radiation spreading to adjacent rooms. Effective but the source continues radiating in the sealed area.

[ ] B.4.3.2 **Decontamination team**: Hazard Control dispatches a decon team to the area. Reduces contamination by 10% per 30 seconds. Team has protective gear (takes 50% reduced radiation damage) but still at risk on prolonged missions in high-radiation zones. Team drawn from crew on that deck.

[ ] B.4.3.3 **Emergency atmospheric flush**: Vent the contaminated deck to space. Radiation contamination drops to 0 instantly. But so does the atmosphere (see B.3.3.4). Most effective for acute contamination after a nuclear torpedo hit.

[ ] B.4.3.4 **Address the source**: Radiation from reactor damage only stops when Engineering repairs the reactor above 60% health. Hazard Control contains; Engineering fixes the root cause. Neither can solve the problem alone.

### B.4.4 Radiation Cross-Station Effects

[ ] B.4.4.1 Crew exposed to radiation develop radiation injuries that appear on Medical's patient list. Severity correlates with exposure duration and intensity. Medical must treat with decontamination (10 seconds) before normal treatment can begin.

[ ] B.4.4.2 Radiation on the engineering deck reduces Engineering crew effectiveness — slower repairs, slower power changes. This creates a feedback loop: reactor damage → radiation → slower repairs → reactor stays damaged. Hazard Control containing the radiation is what breaks the loop.

[ ] B.4.4.3 Radiation on the science deck degrades sensor accuracy by up to 30% (radiation interferes with sensitive equipment). Science sees a "RADIATION INTERFERENCE" warning.

## B.5 STRUCTURAL INTEGRITY SYSTEM

### B.5.1 Structural Model

[ ] B.5.1.1 Each deck section (a group of 2-3 adjacent rooms) has a structural_integrity value (0-100%). Starts at 100%.

[ ] B.5.1.2 Structural integrity reduces from: combat damage to that deck (torpedo: -15 to -25%, beam: -5 to -10%), fire damage over time (intensity 4+: -2% per 30 seconds), hull breach on that section (-10% immediately), explosion (boarder sabotage, reactor event: -20 to -30%).

[ ] B.5.1.3 Structural integrity consequences:
- 100-76%: Normal. No effect.
- 75-51%: STRESSED. Audible hull creaking on that deck (audio for Hazard Control and Security). Cosmetic cracks appear on interior map.
- 50-26%: WEAKENED. Any further hit to this section has a 15% chance of causing a secondary collapse. Crew effectiveness on this section -10%.
- 25-1%: CRITICAL. Any hit has a 40% chance of collapse. Crew effectiveness -30%. Hazard Control gets flashing alert.
- 0%: COLLAPSED. The section is destroyed. All crew in the section take serious injury. Adjacent sections take -15% integrity damage. The section is permanently unusable for the rest of the mission (no repair possible). Equipment in the section is destroyed.

### B.5.2 Structural Reinforcement

[ ] B.5.2.1 During quiet periods, Hazard Control can run "Structural Reinforcement" on weakened sections. Select a section, press [REINFORCE]. Takes 30 seconds. Restores 10% structural integrity per reinforcement cycle. Maximum restoration to 80% (full restoration requires docking).

[ ] B.5.2.2 Reinforcement requires a crew team on that deck (at least 2 crew members). If the deck has been evacuated, reinforcement is not possible until crew return.

[ ] B.5.2.3 This is Hazard Control's proactive activity — between combat, the player strengthens weak spots to prepare for the next engagement. It's never "nothing to do" because there's always something to reinforce.

### B.5.3 Structural Cross-Station Effects

[ ] B.5.3.1 Structural collapse destroys any station equipment in the collapsed section. If weapons systems were in that section, Weapons loses that weapon. If medical bays were there, Medical loses beds. The effect is permanent and devastating.

[ ] B.5.3.2 Collapse creates hull breaches (automatic, major), fires (80% chance, intensity 3), and crew casualties (all crew in section).

[ ] B.5.3.3 Adjacent section integrity damage can cascade — one collapse weakening the next section, which then collapses from a subsequent hit. Hazard Control preventing cascades by reinforcing adjacent sections is critical.

[ ] B.5.3.4 Ops receives "STRUCTURAL WARNING" feed event when any section drops below 50%, enabling Ops to factor structural risk into tactical planning.

## B.6 EMERGENCY SYSTEMS

### B.6.1 Emergency Bulkheads

[ ] B.6.1.1 Hazard Control can seal emergency bulkheads between any two rooms or between decks. Sealing blocks: crew movement, boarder movement, atmosphere exchange, fire spread. More granular than Security's door locks — Hazard Control can isolate individual rooms.

[ ] B.6.1.2 Emergency bulkhead seals are visible to Security on their interior map as red barriers. Security should coordinate with Hazard Control to avoid sealing marines out of a boarding engagement.

[ ] B.6.1.3 Hazard Control can override Security door locks if necessary for safety (e.g., unlock a door to evacuate crew from a fire). This triggers a notification to Security: "HAZCON OVERRIDE: Door [room] unlocked for evacuation."

### B.6.2 Emergency Power

[ ] B.6.2.1 When main power fails on a deck, emergency lighting activates on battery. Each deck's emergency battery lasts 180 seconds. Hazard Control can see battery levels per deck.

[ ] B.6.2.2 Hazard Control can redirect emergency power between decks: drain one deck's battery to extend another. This is a triage decision — which deck needs light and basic life support more?

[ ] B.6.2.3 Decks without any power (main or emergency): complete darkness, no life support, no internal sensors. Security cannot see that deck. Crew effectiveness drops to 20%. Crew take slow morale damage.

### B.6.3 Life Pods

[ ] B.6.3.1 Each deck has life pods with a capacity of 4 crew per pod, 1-2 pods per deck depending on ship size.

[ ] B.6.3.2 If hull integrity reaches a critical threshold (hull <15%), the Captain can order "ABANDON SHIP." This appears on Hazard Control as an evacuation management interface.

[ ] B.6.3.3 Hazard Control manages evacuation order: which decks evacuate first, routing crew to pods, launching pods when full. Each pod launch takes 10 seconds.

[ ] B.6.3.4 Life pod management is a last-resort mechanic. It exists to give Hazard Control a role even in the most extreme scenarios.

## B.7 HAZARD CONTROL UI

### B.7.1 Layout

[ ] B.7.1.1 Three-panel layout.

[ ] B.7.1.2 **Centre: Interior Ship Map** — the primary display. Shows all rooms across all decks with colour-coded overlays. Overlay modes: ATMOSPHERE (O2 levels per room), TEMPERATURE (heat map), CONTAMINATION (radiation/smoke/coolant), STRUCTURAL (integrity per section), FIRE (fire locations and intensity), ALL (combined). Click rooms to target suppression/containment actions. Click connections to control ventilation.

[ ] B.7.1.3 **Left: Deck Status Panel** — summary card per deck showing: O2%, pressure, temperature, contamination type and level, structural integrity, active fires (count and max intensity), crew count, hazard severity (SAFE / CAUTION / HAZARDOUS / CRITICAL / UNINHABITABLE). Cards are colour-coded and sorted by severity (worst deck at top).

[ ] B.7.1.4 **Right: Actions & Alerts Panel** — top: action buttons contextual to selected room/deck (SUPPRESS FIRE / SEAL BULKHEAD / EVACUATE / REINFORCE / VENT / DEPLOY DECON TEAM / EMERGENCY FORCE FIELD). Middle: active hazard list with timers (fire spread countdown, force field remaining time, decon team progress). Bottom: hazard log (chronological list of events).

[ ] B.7.1.5 **Bottom bar**: Suppressant remaining (units), active teams deployed (count), force fields active (count and time remaining), life support status, worst deck condition.

### B.7.2 Audio

[ ] B.7.2.1 Fire started: crackling/alarm
[ ] B.7.2.2 Fire suppressed: hiss/release
[ ] B.7.2.3 Hull breach: explosive decompression whoosh
[ ] B.7.2.4 Force field activated: energy hum
[ ] B.7.2.5 Force field failing (30s remaining): pulsing warning
[ ] B.7.2.6 Radiation alert: Geiger counter clicks increasing in speed
[ ] B.7.2.7 Structural warning (<50%): deep metallic groan
[ ] B.7.2.8 Structural collapse: catastrophic impact/crumble
[ ] B.7.2.9 Deck evacuated: all-clear tone
[ ] B.7.2.10 Deck uninhabitable: klaxon

---

# PART C: CROSS-STATION INTEGRATION OVERHAUL

Every change in this section creates a visible, meaningful connection between two or more stations. The goal: no station acts alone.

## C.1 CAPTAIN → ALL STATIONS

### C.1.1 Captain Target Priority Marker

[ ] C.1.1.1 Captain can click any contact on the tactical map and press [MARK PRIORITY]. The contact gets a distinctive marker: a gold diamond outline visible on EVERY station's map display.

[ ] C.1.1.2 Stations that see the priority marker:
- **Weapons**: Priority target appears at top of target list with gold border. +5% accuracy bonus when engaging a Captain-prioritised target (crew focus).
- **Helm**: Priority target has a range indicator — Helm can see distance to target at all times.
- **Science**: Priority target queued for automatic detailed scan if not already scanned.
- **EW**: Priority target queued for automatic jam if EW has capacity.
- **Ops**: Priority target highlighted in assessment queue.
- **Flight Ops**: Combat drones prefer Captain-prioritised target for attack runs if no other orders.

[ ] C.1.1.3 Only 1 Captain priority target at a time (selecting a new one replaces the old). Captain can clear with [CLEAR PRIORITY].

[ ] C.1.1.4 When a Captain-prioritised target is destroyed, all stations see: "PRIORITY TARGET DESTROYED" notification with a brief audio chime. Morale boost: all crew factors +2% for 60 seconds (the crew feels effective).

### C.1.2 Captain General Orders

[ ] C.1.2.1 Captain can issue ship-wide orders that set behaviour modes for multiple stations simultaneously:

[ ] C.1.2.2 **BATTLE STATIONS**: All stations see red border on their displays. Weapons auto-targets nearest hostile if unassigned. Engineering auto-prioritises weapons and shields power. Security raises alert to combat on all decks. Medical pre-stages triage. Hazard Control pre-positions fire teams.

[ ] C.1.2.3 **SILENT RUNNING** (scout only, see v0.07 2.1): All stations see amber "SILENT" indicator. Systems restrict per stealth rules.

[ ] C.1.2.4 **EVASIVE MANOEUVRES**: Helm gets flashing "EVASIVE" indicator. Ship target profile reduced by 15% (harder to hit). Weapons accuracy reduced by 10% (ship is jinking). Flight Ops drone recovery difficulty +25% (landing on a dodging ship). Lasts until Captain cancels.

[ ] C.1.2.5 **ALL STOP**: Helm throttle forced to 0, heading locked. Used for docking, precise positioning, or emergency situations. Helm must acknowledge to resume control. Ship speed drops to 0. All stations see "ALL STOP" indicator.

[ ] C.1.2.6 **CONDITION GREEN**: Stand down from combat readiness. Opposite of BATTLE STATIONS. Normal operations resume.

## C.2 BOARDING → STATION EFFECTIVENESS

### C.2.1 Boarder Area Impact

[ ] C.2.1.1 When boarders occupy a room, ALL equipment in that room operates at 50% effectiveness. This represents boarders disrupting operations, damaging consoles, and crew being unable to work safely.

[ ] C.2.1.2 If boarders CONTROL a room (all defenders defeated, boarders holding position), effectiveness drops to 0%. The station equipment in that room is offline until boarders are dislodged.

[ ] C.2.1.3 Specific station impacts by room occupation:
- **Bridge occupied**: Captain loses access to all ship-wide orders. Helm controls are locked. Comms is jammed. Game over if bridge is controlled for 60 seconds.
- **Weapons bay occupied**: Affected weapon system fires at 50% rate (contested) or 0% (controlled). Torpedo tubes in that bay cannot load.
- **Engineering occupied**: Reactor controls contested — Engineering can't change power allocation for affected systems. Repair teams in that room are pinned down.
- **Medical bay occupied**: Treatment beds in that bay are unusable. Patients in that bay are at risk (boarders may take hostages — future mechanic).
- **Sensor room occupied**: Science scan speed -50% (contested) or Science station offline (controlled).
- **Flight deck occupied**: All launch/recovery operations halted (contested). Drone command link severed — drones go autonomous (controlled).
- **Comms array room occupied**: Comms signal strength -50% (contested). All channels closed (controlled).

[ ] C.2.1.4 Each occupation effect resolves immediately when boarders are cleared from the room.

[ ] C.2.1.5 The Security player sees occupation effects listed on their UI: "BRIDGE: CONTESTED — Captain/Helm impaired." This gives Security clear priority information — which room matters most.

### C.2.2 Boarding Alerts Cross-Station

[ ] C.2.2.1 When boarding is detected, ALL stations see a boarding indicator in their status bar: "⚠ BOARDING: Deck 4" with intruder count.

[ ] C.2.2.2 Stations in rooms adjacent to boarded rooms see a proximity warning: "INTRUDERS NEARBY — Room [adjacent room]."

[ ] C.2.2.3 Medical gets a casualty prediction: "Boarding engagement in progress — expect 1-3 casualties."

[ ] C.2.2.4 Hazard Control is warned: "Boarders may cause fires or breaches. Pre-stage suppression for Deck 4."

## C.3 ENGINEERING ↔ HAZARD CONTROL DEPENDENCY

[ ] C.3.1 **Fire suppression system is powered by Engineering.** If Engineering has not allocated power to fire suppression (a new system in the power grid), Hazard Control's localised and deck-wide suppression is disabled. Only manual fire teams and ventilation cutoff work without power. This forces Engineering to keep fire suppression powered — and creates a dilemma when power is scarce.

[ ] C.3.2 **Hull breach repair is Engineering's job, containment is Hazard Control's job.** When a breach occurs, Hazard Control deploys emergency force fields and manages atmosphere. Engineering dispatches a repair team to physically patch the breach. Hazard Control's force field buys time (120 seconds); Engineering's repair makes it permanent. If Engineering is too slow, the force field fails and the room decompresses again.

[ ] C.3.3 **Life support power affects all Hazard Control atmospheric recovery.** If Engineering reduces life support power (to divert to weapons during combat), atmospheric recovery across the whole ship slows down. Hazard Control sees this as: "LIFE SUPPORT: [power%] — atmospheric recovery at [rate]." Hazard Control may request Engineering restore life support power via the Quartermaster allocation system.

[ ] C.3.4 **Hazard Control's ventilation decisions affect Engineering repair teams.** If Hazard Control vents a deck to space (clearing contaminants), Engineering repair teams on that deck must evacuate or take vacuum damage. Hazard Control should warn Engineering before venting: a confirmation dialog appears if Engineering has teams deployed on the target deck.

[ ] C.3.5 **Engineering overclock fires.** When Engineering overclock causes a fire (see B.2.1.4), Hazard Control gets the event and must respond. This directly connects Engineering's risk-taking to Hazard Control's workload. An aggressive Engineering player creates more work for Hazard Control.

## C.4 SCIENCE ↔ OPS DEPENDENCY

[ ] C.4.1 **Ops assessments require Science scan data.** Ops cannot assess a contact that Science hasn't scanned. This creates a direct request flow: Ops says "I need a scan on contact Alpha" → Science prioritises that scan → scan completes → Ops runs assessment → tactical intelligence flows to Weapons and Helm.

[ ] C.4.2 **Science scan quality affects Ops assessment quality.** A basic scan gives Ops a basic assessment (shield harmonics only). A detailed scan gives Ops the full suite (shields, systems, behaviour prediction). This incentivises Science to run detailed scans on high-priority targets.

[ ] C.4.3 **Ops sensor focus zone helps Science.** When Ops places a sensor focus zone, Science gets a +25% scan speed bonus within it. This is a reciprocal relationship: Ops helps Science, Science helps Ops.

## C.5 HELM ↔ MULTIPLE STATIONS

[ ] C.5.1 **Helm evasive manoeuvres affect Flight Ops recovery.** When the ship is actively manoeuvring (turn rate > 50% of max), drone recovery success rate drops by 30%. Flight Ops sees: "EVASIVE — Recovery degraded." Helm and Flight Ops must coordinate: "Hold steady for 10 seconds while I recover this drone."

[ ] C.5.2 **Helm speed affects Weapons torpedo accuracy.** Torpedoes launched while the ship is travelling at high speed (>75% max) are slightly more accurate (+5%) because of relative velocity advantages. Torpedoes launched while stationary have normal accuracy.

[ ] C.5.3 **Helm full stop enables Medical evacuation and Quartermaster docking.** Certain cross-station actions (medical shuttle transfers, Quartermaster docking for trade, salvage operations) require the ship to be at full stop or very slow (<10% speed). Helm must cooperate.

[ ] C.5.4 **Helm heading affects shield facing exposure.** Hazard Control's structural reinforcement priority and Engineering's shield focus point both depend on which facing is toward the enemy. Helm's heading relative to threats is information that matters to Engineering, Hazard Control, and Ops. All three should see a "THREAT BEARING" indicator that shows which ship facing is toward the nearest hostile contact.

## C.6 WEAPONS ↔ MULTIPLE STATIONS

[ ] C.6.1 **Weapons torpedo type selection affects combat dynamics visible to multiple stations.** An ion torpedo hit disables enemy systems (Science sees the target's system health drop, Ops sees the vulnerability change). A nuclear torpedo hit creates radiation on the enemy AND potentially on the player's ship if at close range (Hazard Control gets radiation alert, Medical gets casualty warning).

[ ] C.6.2 **Weapons fire rate is visible to Quartermaster.** Each torpedo fired decrements the count. A heavy firing rate triggers Quartermaster awareness: "Torpedo consumption: HIGH — 3 remaining standard." Quartermaster can proactively advise on conservation or plan resupply.

[ ] C.6.3 **Weapons target destruction notifies all stations.** When an enemy is destroyed: Captain sees it, Ops removes assessment, Science removes from contact list, Flight Ops drones retarget, Comms may receive surrender signals from remaining enemies, Quartermaster gets salvage opportunity notification. The destruction event ripples through the whole crew.

## C.7 MEDICAL ↔ HAZARD CONTROL

[ ] C.7.1 **Medical receives injury type predictions from Hazard Control.** When a deck has active hazards (fire, radiation, contamination), Medical sees: "DECK 3 HAZARDS: Fire (intensity 3), smoke contamination. EXPECTED INJURIES: burns, smoke inhalation." Medical can pre-select treatment equipment.

[ ] C.7.2 **Medical can request deck decontamination from Hazard Control.** If patients are arriving with radiation injuries, Medical can request: "Decontaminate Deck 2 — radiation casualties incoming." This appears on Hazard Control as a priority request.

[ ] C.7.3 **Hazard Control can request Medical pre-stage for evacuation.** If a deck is about to be vented or is collapsing, Hazard Control sends: "EVACUATING DECK 4 — expect 3-5 casualties." Medical gets 15 seconds warning to prepare beds.

## C.8 COMMS ↔ OPS ↔ CAPTAIN

[ ] C.8.1 **Comms decoded intelligence routes through Ops for analysis.** When Comms decodes a signal with tactical value (enemy positions, fleet movements, ambush warnings), it routes to Ops. Ops analyses the intel and produces an assessment: "Decoded signal indicates enemy reinforcements arriving from bearing 045 in approximately 3 minutes." This assessed intel is then forwarded to Captain and relevant stations.

[ ] C.8.2 **Ops can request specific Comms actions.** Ops can send Comms a request: "Need frequency scan of bearing 120-180 — expecting enemy communications." Comms sees this as a suggested action, not an order.

[ ] C.8.3 **Captain mission decisions are informed by Ops analysis.** When a mission is offered, Ops can provide a feasibility assessment: "Mission distance: 8,000 units. Travel time at current speed: 90 seconds. Threat level at destination: MEDIUM. Recommendation: ACCEPT." Captain sees this alongside the mission offer.

## C.9 EW ↔ OPS ↔ WEAPONS

[ ] C.9.1 **EW jamming success visible to Ops.** When EW successfully jams an enemy, Ops sees the effect in their assessment: "Target [name] JAMMED — sensors degraded. Accuracy bonus available." Ops can time coordination bonuses around EW jam windows.

[ ] C.9.2 **EW intrusion success provides data to Ops.** If EW successfully intrudes an enemy system, Ops receives detailed system data without needing a Science scan. This creates an alternative data path: Science scans from outside, or EW intrudes from the electromagnetic spectrum.

[ ] C.9.3 **Weapons firing reveals ship position to enemies.** When Weapons fires beams or torpedoes, the ship's emission signature spikes. EW can mask this (+15% to mask cost during firing), or the ship can be detected more easily. Ops should factor this into engagement planning: "Fire only when EW has mask active."

## C.10 FLIGHT OPS ↔ MULTIPLE STATIONS

[ ] C.10.1 **Scout drone contacts are shared to Science.** Contacts detected by scout drones appear on Science's contact list with a [DRONE] tag. Science can scan drone-detected contacts. This extends Science's effective reach.

[ ] C.10.2 **Rescue drone survivors go to Medical.** When a rescue drone returns with survivors, Medical gets an alert: "INCOMING PATIENTS: 3 survivors from rescue drone [callsign]. ETA: 30 seconds." Survivors arrive as patients with varying injuries.

[ ] C.10.3 **Combat drone kills count as Weapons kills for crew morale.** When a drone destroys an enemy, the morale boost triggers shipwide (same as a direct kill). Crew feels effective.

[ ] C.10.4 **ECM drone effects are visible to EW.** ECM drone jamming stacks with ship EW jamming. EW sees the combined effectiveness: "Ship jam: 40%. Drone jam: 25%. Total: 55% degradation to target sensors."

## C.11 SECURITY ↔ HAZARD CONTROL

[ ] C.11.1 **Security door locks and Hazard Control bulkheads interact.** If Hazard Control seals a bulkhead, Security cannot open that door. If Security locks a door, Hazard Control can override for safety reasons but Security is notified. Both stations see each other's door/bulkhead states on the interior map in different colours (Security = blue, Hazard Control = orange).

[ ] C.11.2 **Security marine teams are affected by hazards.** Marines in rooms with fire intensity 3+ take damage. Marines in rooms with radiation take radiation damage. Marines in depressurised rooms are in serious danger. Security should coordinate with Hazard Control: "Clear the fire on Deck 4 before I send marines in."

[ ] C.11.3 **Boarding parties can cause fires.** Boarder sabotage actions create fires (20% chance per boarder action). These fires appear on Hazard Control's display immediately. During boarding, Hazard Control may be fighting fires on the same deck Security is fighting boarders.

[ ] C.11.4 **Hazard Control emergency vent can affect boarders.** Venting a deck to space kills atmosphere for everyone — crew AND boarders. If Security can evacuate crew from a boarded deck, Hazard Control venting that deck is devastating to boarders (they take vacuum damage). This is a coordinated tactic: Security evacuates, Hazard Control vents, boarders die or retreat to another deck.

## C.12 QUARTERMASTER ↔ HAZARD CONTROL

[ ] C.12.1 **Fire suppressant is a Quartermaster resource.** Suppressant depletion is tracked by Quartermaster alongside other consumables. Quartermaster can resupply suppressant at vendors.

[ ] C.12.2 **Hazard Control can request suppressant from Quartermaster** via the allocation request system (same as Engineering requesting repair materials).

[ ] C.12.3 **Environmental damage creates resource consumption.** Hull breach repairs consume Engineering repair materials. Fire suppression consumes suppressant. Decontamination consumes medical supplies (minor amount). All of this flows to Quartermaster tracking. A rough engagement that creates fires, breaches, and radiation costs resources across multiple categories — Quartermaster feels the impact of every torpedo hit.

---

# PART D: TEST TARGETS

| Test File | Target | Audit |
|-----------|--------|-------|
| [ ] D.1 tests/test_ops_assessment.py | 30+ tests (battle assessment, shield harmonics, system vulnerability, behaviour prediction, threat levels) | |
| [ ] D.2 tests/test_ops_coordination.py | 25+ tests (weapons-helm sync, sensor focus, damage coordination, evasion alert, bonuses applied correctly) | |
| [ ] D.3 tests/test_ops_mission.py | 15+ tests (mission tracking, station advisory, progress updates) | |
| [ ] D.4 tests/test_ops_feed.py | 15+ tests (information feed filtering, all event types appear, severity coding) | |
| [ ] D.5 tests/test_fire_system.py | 30+ tests (fire model, intensity, spread, suppression types, suppressant resource, cross-station effects) | |
| [ ] D.6 tests/test_atmosphere.py | 25+ tests (O2, pressure, temperature, contamination, hull breach, ventilation states, emergency vent) | |
| [ ] D.7 tests/test_radiation.py | 20+ tests (sources, zones, containment, decon team, flush, cross-station effects) | |
| [ ] D.8 tests/test_structural.py | 20+ tests (integrity model, damage, reinforcement, collapse, cascade, cross-station effects) | |
| [ ] D.9 tests/test_hazcon_emergency.py | 15+ tests (bulkheads, emergency power, life pods) | |
| [ ] D.10 tests/test_captain_orders.py | 20+ tests (priority target marker visible on all stations, general orders affect all stations, each order's specific effects) | |
| [ ] D.11 tests/test_boarding_impact.py | 20+ tests (room occupation reduces effectiveness, each room type's specific impact, controlled vs contested, clearing restores function) | |
| [ ] D.12 tests/test_cross_station_flow.py | 35+ tests (Eng↔HazCon dependency, Science↔Ops flow, Helm effects on other stations, weapon fire ripples, Medical↔HazCon, Comms→Ops→Captain, EW↔Ops, FlightOps contacts→Science, Security↔HazCon coordination) | |
| Total | 270+ new tests | |

---

# BUILD ORDER

| Phase | Part | Description | Risk | Depends On |
|-------|------|-------------|------|------------|
| A.1 | A.1 | Rename Tactical → Operations, station setup | Low | Role registry |
| A.2 | A.2 | Enemy analysis system | High | Science scan system |
| A.3 | A.3 | Coordination bonuses | High | Weapons, Helm, Science, EW |
| A.4 | A.4 | Mission management | Medium | Comms missions |
| A.5 | A.5 | Operations UI | Medium | A.2-A.4 |
| B.1 | B.1 | Rename DC → Hazard Control, station setup | Low | Role registry |
| B.2 | B.2 | Fire system | High | Interior map, Engineering |
| B.3 | B.3 | Atmosphere system | High | Interior map, Engineering |
| B.4 | B.4 | Radiation system | Medium | B.3, Engineering, Medical |
| B.5 | B.5 | Structural integrity | Medium | Interior map |
| B.6 | B.6 | Emergency systems | Medium | B.2-B.5 |
| B.7 | B.7 | Hazard Control UI | Medium | B.2-B.6 |
| C.1 | C.1-C.2 | Captain orders + boarding impact | Medium | Security, all stations |
| C.2 | C.3-C.5 | Engineering/Science/Helm integrations | Medium | Ops, HazCon |
| C.3 | C.6-C.9 | Weapons/Medical/Comms/EW integrations | Medium | Ops, HazCon |
| C.4 | C.10-C.12 | FlightOps/Security/QM integrations | Medium | HazCon |
| D | D.1-D.12 | Full test suite | Medium | Everything |

**Commit after each part.** Format: "v0.08-[section]: description"

**Pytest after each part.** Zero regressions.

---

# STOP CONDITIONS

- Ops coordination bonuses stack in unintended ways (e.g., sync + prediction + focus = overpowered accuracy)
- Fire spread rate makes the ship uninhabitable in under 2 minutes regardless of Hazard Control action
- Atmospheric simulation creates server performance issues (per-room calculations every tick across 30+ rooms)
- Structural collapse cascades destroy the entire ship from a single torpedo hit
- Cross-station notifications flood station UIs with too many alerts (more than 3 active notifications = alert fatigue)
- Boarding room occupation disables a station permanently (it should restore immediately when cleared)
- Ops information feed scrolls too fast to read during combat (rate limit or filtering needed)
- Hazard Control has nothing to do during non-combat periods (structural reinforcement is the idle-time activity — if this isn't generating enough work, increase passive degradation rate)
- Any station crashes or errors when Ops or Hazard Control station is uncrewed

---

# CLASSROOM NOTES

**Operations** suits the analytical student — the one who likes understanding systems, spotting patterns, and thinking strategically. They don't need fast reflexes; they need good observation and clear communication. Ops is the student who says "I noticed the enemy always turns left after firing — we should approach from the right."

**Hazard Control** suits the crisis management student — the one who stays calm under pressure, makes fast decisions about competing priorities, and thinks spatially. They're managing a real-time environmental puzzle. Hazard Control is the student who says "Deck 3 is on fire and Deck 5 is breached — I'll seal Deck 5 and suppress Deck 3 because Deck 3 has more crew."

**Together**, these two stations fill the gap that the playtest exposed: Azu had nothing to do because nothing threatened the ship's interior. With Hazard Control, every torpedo hit creates environmental work. With Ops, every sensor contact creates analytical work. Neither station is ever truly idle.

**Cross-station integration** means students MUST communicate to play well. The game now punishes silence. A crew that doesn't talk has:
- No Ops coordination bonuses (Weapons and Helm don't sync)
- Engineering and Hazard Control stepping on each other (venting a deck while repair teams are on it)
- Security sending marines into fires
- Captain making blind decisions without Ops analysis
- Medical caught off-guard by casualties from uncontained hazards

The crew that talks wins. That's the pedagogical core of Starbridge.

---

*End of v0.08 Specification*
*Total audit checkboxes: 287*
*Total test target: 270+ new tests*
