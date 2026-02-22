Read ALL of these files before doing anything:

1. .ai/SYSTEM_PROMPT.md
2. .ai/STATE.md
3. .ai/CONVENTIONS.md
4. .ai/DECISIONS.md
5. .ai/LESSONS.md
6. docs/SCOPE_v005.md (for context on what exists)

This is v0.06.1 — a complete overhaul of the Medical station. The 
current Medical system tracks casualties as numbers per deck. The 
new system tracks individual named crew members with specific 
injuries, body regions, severity levels, treatment options, and 
death mechanics. This is the most significant single-station 
overhaul in the project.

Read the current Medical implementation fully before writing any 
code:
- server/game_loop_medical.py
- server/medical.py (if it exists)
- server/models/ (check for crew models)
- client/medical/medical.js
- client/medical/medical.css
- client/medical/index.html
- Any test files: tests/test_medical*.py, tests/test_game_loop_medical*.py

Understand how Medical currently works — what messages it sends and 
receives, how crew state is tracked, how treatment works, how the 
triage puzzle integrates, and how crew factor is calculated. The new 
system must replace all of this while maintaining every external 
interface (crew factor feeding into ship systems, damage events 
creating casualties, medical supplies from docking, save/resume 
serialisation).

=============================================================
PART 1: CREW ROSTER SYSTEM (server/models/crew.py — new file)
=============================================================

Build a crew roster that generates named individuals at game start.

CREW MEMBER MODEL:

@dataclass
class CrewMember:
    id: str                    # Unique ID: "crew_001", "crew_002"
    first_name: str            # From diverse name pool
    surname: str               # From diverse name pool
    rank: str                  # Rank title
    rank_level: int            # 1-7 for sorting
    deck: int                  # Assigned deck (1-5 typically)
    duty_station: str          # Ship system: "engines", "weapons", etc.
    status: str                # "active", "injured", "critical", "dead"
    injuries: list[Injury]     # Current injuries
    location: str              # "deck_3", "medical_bay", "morgue"
    treatment_bed: int | None  # Bed number if in medical bay (None if not)

@dataclass
class Injury:
    id: str                    # Unique ID: "inj_001"
    type: str                  # "internal_bleeding", "fracture", etc.
    body_region: str           # "head", "torso", "left_arm", "right_arm",
                               # "left_leg", "right_leg"
    severity: str              # "critical", "serious", "moderate", "minor"
    description: str           # Human-readable: "Shrapnel wound to left arm"
    caused_by: str             # "hull_breach", "explosion", "fire", etc.
    tick_received: int         # When the injury occurred
    degrade_timer: float       # Seconds until severity worsens
    death_timer: float | None  # Seconds until death (critical only)
    treatment_type: str        # Required treatment type
    treatment_duration: float  # Seconds to treat
    treated: bool              # Has this been treated?
    treating: bool             # Currently being treated?

NAME GENERATION:

Create two lists in server/models/crew_names.py:

FIRST_NAMES — 200 names, evenly split across diverse cultural 
backgrounds. Include names from: English, Spanish, Chinese, Indian, 
Japanese, Korean, Arabic, African (various), Russian, Pacific 
Islander, Indigenous Australian, and other backgrounds. Mix of 
traditionally masculine and feminine names. Examples: "Sarah", 
"Kenji", "Amara", "Dmitri", "Aroha", "Priya", "Carlos", "Yuki", 
"Oluwaseun", "Mei", "Aleksandra", "Tariq", "Ngaire", etc.

SURNAMES — 200 surnames with similar diversity. Examples: "Chen", 
"Okafor", "Martinez", "Tanaka", "Krishnamurthy", "Williams", 
"Al-Rashid", "Kowalski", "Nakamura", "Adeyemi", "Johansson", etc.

Names are randomly paired at game start. No duplicates within a 
single game's crew.

RANKS:

| Rank | Level | Count per ship class (approx) |
|------|-------|-------------------------------|
| Commander | 7 | 0-1 (department heads only) |
| Lt. Commander | 6 | 1-2 |
| Lieutenant | 5 | 2-4 |
| Sub-Lieutenant | 4 | 2-4 |
| Chief Petty Officer | 3 | 3-5 |
| Petty Officer | 2 | 4-8 |
| Crewman | 1 | remainder |

Total crew count comes from the ship class JSON (already defined). 
Distribute across ranks with higher ranks being rarer. Distribute 
across decks roughly evenly. Assign duty stations based on deck 
(Deck 1 crew → bridge systems, Deck 2 → weapons/sensors, Deck 3 → 
engineering, etc. — check how decks map to systems in the existing 
code).

CREW ROSTER:

@dataclass
class CrewRoster:
    members: dict[str, CrewMember]  # id → CrewMember
    
    @classmethod
    def generate(cls, crew_count: int, ship_class: str) -> 'CrewRoster':
        """Generate a full crew roster for the given ship class."""
        ...
    
    def get_by_deck(self, deck: int) -> list[CrewMember]:
        ...
    
    def get_by_status(self, status: str) -> list[CrewMember]:
        ...
    
    def get_by_duty_station(self, station: str) -> list[CrewMember]:
        ...
    
    def get_injured(self) -> list[CrewMember]:
        """All crew with at least one injury, sorted by worst severity."""
        ...
    
    def get_active_count(self) -> int:
        ...
    
    def get_dead_count(self) -> int:
        ...
    
    def crew_factor_for_system(self, system: str) -> float:
        """Calculate crew factor (0.0-1.0) for a ship system based on 
        active crew assigned to that duty station."""
        ...
    
    def serialise(self) -> dict:
        ...
    
    @classmethod
    def deserialise(cls, data: dict) -> 'CrewRoster':
        ...

CREW FACTOR INTEGRATION:

The existing crew factor calculation (however it works currently) 
must be replaced by CrewRoster.crew_factor_for_system(). The formula:

    factor = active_crew_at_station / expected_crew_at_station

Where active_crew = crew assigned to that duty station who are 
status "active" (not injured, not dead, not in medical bay). If 
a crew member is in medical bay being treated, they don't count 
as active. If they're injured but still at their station (minor 
injuries), they count at 50% effectiveness.

This means Medical's decisions directly affect every other station's 
performance. Treating the engineer restores Engineering's crew 
factor. Prioritising the weapons technician over the engineer is a 
tactical choice.

TESTS: Write tests/test_crew_roster.py
- Roster generation produces correct crew count
- Names are unique within a roster
- Ranks distribute correctly
- Deck assignments are roughly even
- Duty station mapping works
- crew_factor_for_system returns 1.0 with full healthy crew
- crew_factor drops when crew are injured/dead
- Injured crew at 50% effectiveness for minor injuries
- Crew in medical bay don't count as active
- Serialise/deserialise round-trip
Target: 30+ tests

=============================================================
PART 2: INJURY SYSTEM (server/models/injuries.py — new file)
=============================================================

INJURY CATALOGUE:

Define all possible injuries organised by cause. When a damage 
event occurs, the system rolls against crew on the affected deck 
to determine who gets hurt and what injuries they receive.

INJURY DEFINITIONS BY CAUSE:

Hull breach injuries:
- Decompression syndrome (torso, critical, surgery 45s)
  "Rapid decompression — loss of consciousness, tissue damage"
- Barotrauma (torso, serious, intensive_care 40s)
  "Pressure differential injury to lungs"
- Impact fracture (random limb, serious, surgery 35s)
  "Bone fracture from debris impact"
- Lacerations from debris (random region, moderate, first_aid 15s)
  "Multiple cuts from flying debris"
- Hypothermia (torso, moderate, stabilise 20s)
  "Core temperature drop from vacuum exposure"
- Concussion (head, moderate, stabilise 15s)
  "Head impact during decompression event"

Explosion injuries:
- Severe burns (random region, critical, intensive_care 50s)
  "Third-degree burns covering [region]"
- Shrapnel wound (random region, serious, surgery 35s)
  "Embedded shrapnel fragments in [region]"
- Blast concussion (head, serious, stabilise 25s)
  "Traumatic brain injury from blast wave"
- Internal bleeding (torso, critical, surgery 45s)
  "Blunt force trauma causing internal haemorrhage"
- Ruptured eardrum (head, moderate, first_aid 10s)
  "Tympanic membrane rupture from overpressure"
- Flash burns (random region, moderate, first_aid 15s)
  "Superficial burns from flash heat"

Fire injuries:
- Severe burns (random region, critical, intensive_care 50s)
  "Third-degree burns from sustained fire exposure"
- Moderate burns (random region, serious, surgery 30s)
  "Second-degree burns to [region]"
- Smoke inhalation (torso, serious, stabilise 25s)
  "Toxic smoke damage to airways"
- Minor burns (random region, moderate, first_aid 15s)
  "First-degree burns to [region]"
- Heat exhaustion (torso, minor, first_aid 10s)
  "Overheating and dehydration from fire proximity"

Boarding combat injuries:
- Ballistic wound (random region, critical, surgery 45s)
  "Projectile wound to [region] — severe tissue damage"
- Ballistic wound (random region, serious, surgery 35s)
  "Projectile wound to [region] — controlled bleeding"
- Blunt trauma (random region, serious, stabilise 25s)
  "Blunt force injury to [region]"
- Blade wound (random region, serious, surgery 30s)
  "Deep laceration to [region] from edged weapon"
- Concussion (head, moderate, stabilise 15s)
  "Head impact during close combat"
- Bruising and contusions (random region, minor, first_aid 10s)
  "Multiple contusions from physical combat"

Radiation injuries:
- Acute radiation syndrome (whole_body, serious, intensive_care 60s)
  "High-dose radiation exposure — nausea, immune suppression"
  NOTE: This injury is special — it has DELAYED ONSET. Appears as 
  minor, automatically degrades to moderate after 60s, serious 
  after 120s, critical after 180s regardless of treatment. Treatment 
  slows degradation but doesn't stop it. Only intensive_care halts 
  progression entirely.
- Radiation burns (random region, moderate, stabilise 20s)
  "Localised radiation burn to [region]"
- Radiation sickness (torso, moderate, stabilise 20s)
  "Nausea, fatigue from moderate radiation exposure"

Contagion injuries:
- Infection stage 1 (torso, moderate, quarantine 30s + stabilise 20s)
  "Pathogen detected — early stage infection"
  NOTE: SPREADS. Every 60s, if an infected crew member is on the 
  same deck as uninfected crew and is NOT quarantined, there is a 
  30% chance per adjacent crew member of transmission. Quarantine 
  stops spread. Treatment cures.
- Infection stage 2 (torso, serious, quarantine 30s + surgery 40s)
  "Advanced infection — organ involvement"
- Infection stage 3 (torso, critical, quarantine 30s + intensive_care 60s)
  "Systemic infection — multi-organ compromise"

System malfunction injuries (electrical/mechanical failures):
- Electrical burn (random limb, moderate, first_aid 15s)
  "Electrical discharge burn to [region]"
- Crush injury (random limb, serious, surgery 35s)
  "Limb caught in failed mechanism"
- Electrical shock (torso, serious, stabilise 25s)
  "Cardiac involvement from electrical shock"

INJURY GENERATION:

def generate_injuries(cause: str, deck: int, roster: CrewRoster, 
                      severity_scale: float = 1.0) -> list[tuple[str, Injury]]:
    """
    Generate injuries for crew on the affected deck.
    
    Returns list of (crew_member_id, Injury) tuples.
    
    Not everyone gets hurt. Roll for each crew member on the deck:
    - Base chance of injury: 40% per crew member
    - severity_scale multiplier (difficulty preset affects this)
    - Roll for number of injuries (1-2 per affected crew member)
    - Roll for specific injury from the cause's injury pool
    - Roll for body region (where "random" is specified)
    - Assign severity, description, timers
    """
    ...

DEGRADATION TIMERS:

Each severity has a degrade timer — how long until the injury 
worsens by one level:

| Severity | Degrade Timer | Death Timer |
|----------|--------------|-------------|
| Minor | 300s (5 min) → moderate | None |
| Moderate | 180s (3 min) → serious | None |
| Serious | 120s (2 min) → critical | None |
| Critical | N/A (already worst) | 240s (4 min) → death |

These timers tick DOWN every game tick. When degrade_timer reaches 
0, the injury severity upgrades and the timer resets for the new 
level. When death_timer reaches 0, the crew member dies.

STABILISE treatment resets the degrade timer to maximum for that 
severity (buys time but doesn't fix the injury). Full treatment 
(surgery, intensive_care, etc.) resolves the injury entirely.

TESTS: Write tests/test_injuries.py
- Injury generation produces valid injuries for each cause type
- Not all crew on a deck are injured (probabilistic)
- Body regions are valid
- Severity levels are valid
- Degradation timers count down correctly
- Injuries degrade through severity levels on schedule
- Critical injuries trigger death when death_timer expires
- Stabilise resets degrade timer
- Treatment resolves injury
- Radiation has delayed onset progression
- Contagion spreads to adjacent crew on same deck
- Quarantine prevents contagion spread
- Serialise/deserialise round-trip
Target: 40+ tests

=============================================================
PART 3: MEDICAL GAME LOOP (server/game_loop_medical.py — rewrite)
=============================================================

Replace the existing medical game loop with one that manages 
individual crew and injuries.

MEDICAL STATE:

treatment_beds: int           # Max beds (from ship class: scout=2, 
                               # corvette=3, frigate=4, cruiser=5, 
                               # battleship=6, medical_ship=8, 
                               # carrier=5)
occupied_beds: dict[int, str]  # bed_number → crew_member_id
treatment_queue: list[str]     # crew_member_ids waiting for beds
active_treatments: dict[str, Treatment]  # crew_id → active treatment
medical_supplies: float        # 0-100%, consumed by treatments
quarantine_slots: int          # Max quarantine (2 for most ships, 
                               # 4 for medical ship)
quarantine_occupied: dict[int, str]  # slot → crew_member_id
morgue: list[str]              # crew_member_ids of dead crew

@dataclass
class Treatment:
    crew_member_id: str
    injury_id: str
    treatment_type: str
    duration: float           # Total seconds
    elapsed: float            # Seconds completed
    puzzle_required: bool     # Does this treatment need a puzzle?
    puzzle_completed: bool    # Has the puzzle been done?

TICK PROCESSING (every game tick):

def tick(roster: CrewRoster, game_state: dict) -> list[Action]:
    actions = []
    
    # 1. Tick all injury timers
    for member in roster.get_injured():
        for injury in member.injuries:
            if injury.treated or injury.treating:
                continue
            
            # Degrade timer
            injury.degrade_timer -= tick_interval
            if injury.degrade_timer <= 0:
                upgrade_severity(injury)
                actions.append(severity_changed_action(member, injury))
            
            # Death timer (critical only)
            if injury.severity == 'critical' and injury.death_timer is not None:
                injury.death_timer -= tick_interval
                if injury.death_timer <= 0:
                    kill_crew_member(member, roster)
                    actions.append(death_action(member, injury))
    
    # 2. Tick contagion spread
    for member in roster.get_by_status('injured'):
        for injury in member.injuries:
            if injury.type.startswith('infection') and member.location != 'quarantine':
                maybe_spread_contagion(member, roster, actions)
    
    # 3. Tick active treatments
    for crew_id, treatment in active_treatments.items():
        if treatment.puzzle_required and not treatment.puzzle_completed:
            continue  # Waiting for puzzle completion
        treatment.elapsed += tick_interval
        if treatment.elapsed >= treatment.duration:
            complete_treatment(crew_id, treatment, roster)
            actions.append(treatment_complete_action(crew_id, treatment))
    
    # 4. Auto-admit from queue if beds available
    while treatment_queue and len(occupied_beds) < treatment_beds:
        next_id = treatment_queue.pop(0)
        admit_to_bed(next_id, roster)
        actions.append(admitted_action(next_id))
    
    # 5. Recalculate crew factors
    update_crew_factors(roster, game_state)
    
    return actions

MESSAGE HANDLERS:

medical.admit_patient { crew_id }
  — Move crew member from their deck to medical bay, assign a bed 
    if available, otherwise add to queue. Crew member's duty station 
    loses their crew factor contribution immediately.

medical.start_treatment { crew_id, injury_id, treatment_type }
  — Begin treating a specific injury on a specific crew member.
    Crew member must be in a bed. Treatment type must match the 
    injury's required treatment. Consumes medical supplies based 
    on treatment type:
    - first_aid: 2% supplies
    - stabilise: 3% supplies
    - surgery: 8% supplies
    - intensive_care: 10% supplies
    - quarantine: 5% supplies (one-time)
    If treatment requires a puzzle, trigger the puzzle first.
    Treatment timer starts after puzzle completion.

medical.stabilise { crew_id, injury_id }
  — Quick stabilise: resets the injury's degrade timer without 
    resolving it. Crew member does NOT need a bed. Can be done on 
    deck. Buys time. Costs 3% supplies.

medical.quarantine { crew_id }
  — Move infected crew member to quarantine slot. Stops contagion 
    spread. Must have quarantine slot available. If no slot 
    available, return error.

medical.discharge_patient { crew_id }
  — Move treated crew member from medical bay back to their deck. 
    Only if all injuries are treated. Frees the bed. Crew factor 
    for their duty station is restored.

medical.set_triage_priority { crew_ids: list }
  — Reorder the treatment queue. Medical player can drag to 
    reorder who gets the next available bed.

DAMAGE EVENT INTEGRATION:

When any damage event occurs (hull hit, explosion, fire, boarding, 
radiation, contagion, system malfunction), the responsible game loop 
module calls:

    injuries = generate_injuries(cause, deck, roster, severity_scale)
    for crew_id, injury in injuries:
        roster.members[crew_id].injuries.append(injury)
        roster.members[crew_id].status = worst_status(roster.members[crew_id])
        broadcast_to_roles(['medical'], 'medical.casualty', {
            'crew_id': crew_id,
            'crew_name': member.display_name,
            'injury': injury.to_dict(),
            'deck': member.deck
        })

The Medical client receives individual casualty notifications in 
real-time. A new casualty appearing in the list with a critical 
severity and ticking death timer creates urgency.

Also broadcast a summary to Captain:
    broadcast_to_roles(['captain'], 'ship.casualty_report', {
        'crew_name': member.display_name,
        'severity': injury.severity,
        'deck': member.deck,
        'description': injury.description
    })

SUPPLY INTEGRATION WITH DOCKING:

When docked at a station with medical services, medical_supplies 
restores to 100% over the service duration (already defined in 
v0.05f). If supplies reach 0%, no treatments can be started. 
Stabilise still works at 0% (emergency measure, no supplies needed) 
but full treatments require supplies.

SERIALISE/DESERIALISE:

The entire medical state must serialise for save/resume:
- All crew roster state (every crew member, every injury, every timer)
- Bed assignments
- Treatment queue
- Active treatments and their progress
- Supply level
- Quarantine state
- Morgue list

TESTS: Write tests/test_game_loop_medical_v2.py
- Damage event generates casualties
- Casualties appear in correct severity
- Injury timers degrade correctly
- Critical timer leads to death
- Stabilise resets timers
- Treatment starts and completes
- Puzzle integration works (treatment waits for puzzle)
- Bed management (admit, queue when full, discharge)
- Quarantine prevents contagion spread
- Supply consumption is correct
- Cannot treat at 0% supplies (except stabilise)
- Crew factor updates when crew injured/treated/killed
- Death removes crew permanently
- Captain receives casualty notifications
- Multiple simultaneous injuries on one crew member
- Treatment priority queue reordering
- Serialise/deserialise round-trip of full medical state
- Radiation delayed onset progression
- Contagion spread mechanics
Target: 60+ tests

=============================================================
PART 4: MEDICAL CLIENT UI (client/medical/ — full rewrite)
=============================================================

Complete overhaul of the Medical station UI. Wire aesthetic 
throughout. This is the most visually complex station in the game.

LAYOUT:

┌─────────────────────────────┬─────────────────────────────┐
│ CASUALTY LIST               │ PATIENT DETAIL              │
│                             │                             │
│ Sort: [URGENCY] [DECK]     │ Name, Rank, Station, Deck   │
│       [NAME] [ARRIVAL]     │                             │
│                             │ ┌───────────────────┐      │
│ Filter: [ALL] [CRIT] [SER] │ │   BODY DIAGRAM    │      │
│         [MOD] [MIN]        │ │                   │      │
│ Deck: [ALL][1][2][3][4][5] │ │   Wireframe human │      │
│                             │ │   with highlighted │      │
│ ┌─ ▶ Lt. Chen ──────────┐ │ │   injury regions  │      │
│ │ CRITICAL — 3:42 remain │ │ │                   │      │
│ │ Internal bleeding      │ │ └───────────────────┘      │
│ │ Deck 3 — Engineering   │ │                             │
│ └────────────────────────┘ │ INJURIES:                    │
│ ┌─ ▶ Ens. Okafor ───────┐ │ ▶ Internal bleeding [CRIT]  │
│ │ SERIOUS — 1:48 remain  │ │   Torso — haemorrhage      │
│ │ Compound fracture      │ │   Death in: 3:42           │
│ │ Deck 2 — Weapons       │ │   [SURGERY 45s] [STABILISE]│
│ └────────────────────────┘ │                             │
│ ┌─ CPO Martinez ─────────┐ │ ▶ Fractured ribs [SERIOUS] │
│ │ MODERATE — 2:56 remain │ │   Torso — left side        │
│ │ Smoke inhalation       │ │   Degrades in: 1:48        │
│ │ Deck 3 — Engineering   │ │   [SURGERY 35s] [STABILISE]│
│ └────────────────────────┘ │                             │
│                             │                             │
│ [MORE CASUALTIES...]        │                             │
│                             │                             │
├─────────────────────────────┼─────────────────────────────┤
│ BEDS: ●●○○ 2/4 occupied    │ TREATMENT PROGRESS          │
│ QUEUE: 1 waiting            │ Lt. Chen — Surgery — 34/45s │
│ SUPPLIES: ████████░░ 80%   │ ████████████████░░░░░ 76%   │
│ QUARANTINE: ○○ 0/2          │                             │
│ MORGUE: 1                   │ [ADMIT SELECTED] [DISCHARGE]│
│ CREW: 18/22 active          │ [QUARANTINE]                │
└─────────────────────────────┴─────────────────────────────┘

CASUALTY LIST (left panel):

- Each casualty is a card showing: name, rank, worst injury 
  severity, worst injury description, deck, duty station, timer 
  (degrade or death countdown)
- Cards are colour-coded by worst severity:
  Critical: red border, pulsing
  Serious: amber border
  Moderate: yellow border
  Minor: dim border
- Selected casualty is highlighted with bright border
- Click a casualty to show their detail in the right panel
- Sort buttons change list order:
  URGENCY = worst severity first, then shortest timer
  DECK = grouped by deck number
  NAME = alphabetical
  ARRIVAL = order injured (newest first)
- Filter buttons show/hide by severity
- Deck filter shows only casualties from a specific deck
- If a casualty's timer runs out and they die, their card flashes 
  red then fades to grey with "DECEASED" overlay
- New casualties appear at the top with a flash animation and 
  audio alert (if audio enabled)

BODY DIAGRAM (right panel, top):

A wireframe human figure drawn on a canvas element. Simple but 
recognisable — head circle, torso rectangle, limb rectangles. 
Wire aesthetic (stroke only, no fill, monospace labels).

Body regions:
- Head: circle at top
- Torso: rectangle, centre mass
- Left arm: rectangle, left side
- Right arm: rectangle, right side
- Left leg: rectangle, lower left
- Right leg: rectangle, lower right

Each region is highlighted based on injury:
- No injury: dim outline (dark grey)
- Minor injury: faint yellow fill
- Moderate injury: amber fill, slow pulse
- Serious injury: orange fill, moderate pulse
- Critical injury: red fill, fast pulse

If a region has MULTIPLE injuries, show the worst severity colour 
and add a small number badge showing injury count.

Click a body region to filter the injury list below to only show 
injuries for that region.

WHOLE BODY injuries (radiation, contagion) highlight ALL regions.

INJURY LIST (right panel, middle):

Below the body diagram, list all injuries for the selected patient:

Each injury shows:
- Type name and severity badge [CRITICAL] [SERIOUS] [MODERATE] [MINOR]
- Body region
- Description text
- Timer: "Death in: 3:42" (critical) or "Degrades in: 1:48" (others)
- Treatment buttons:
  - The appropriate treatment button for this injury type
    (e.g., [SURGERY 45s] for internal bleeding)
  - [STABILISE 15s] always available (buys time, doesn't fix)
  - Buttons are disabled if: no bed available, insufficient 
    supplies, another treatment is already in progress on this 
    patient
- If treatment is in progress: progress bar replacing the buttons

TREATMENT FLOW:

1. Player clicks a casualty in the list (selects patient)
2. Body diagram highlights their injuries
3. Player clicks [ADMIT] to move them to a medical bed
   — If no bed available, they join the queue
   — Admission is instant (patient teleports to medical bay)
4. Player clicks a treatment button on a specific injury
5. If the treatment requires a puzzle (surgery, intensive_care):
   — Triage puzzle launches (existing puzzle mechanic)
   — Puzzle difficulty scales with injury severity
   — Puzzle success → treatment timer starts
   — Puzzle failure → treatment takes 50% longer (complications)
6. Treatment timer counts down with progress bar
7. On completion: injury is marked as treated
   — If crew member has more untreated injuries, they stay in bed
   — If all injuries treated, [DISCHARGE] button becomes active
8. Player clicks [DISCHARGE] → crew member returns to their deck
   — Bed is freed for next patient in queue
   — Crew factor for their duty station is restored

QUARANTINE FLOW:

1. Player spots a contagion injury on a crew member
2. Player clicks [QUARANTINE] → moves them to quarantine slot
3. Quarantine setup takes 30s (shown as progress bar)
4. Once quarantined, contagion cannot spread from this patient
5. Treatment can proceed while in quarantine
6. After treatment, discharge from quarantine back to deck

STATUS BAR (bottom):

- Beds: filled circles for occupied, empty for available
- Queue count
- Supplies: percentage bar (changes colour: green >50%, amber 
  25-50%, red <25%)
- Quarantine: slots used/available
- Morgue: count (click to expand a list of deceased crew with 
  name, rank, cause of death, time of death)
- Crew: active/total count

AUDIO INTEGRATION:

- New casualty arriving: alert tone (scales with severity — 
  soft ping for minor, urgent alarm for critical)
- Death: solemn tone
- Treatment complete: positive chime
- Timer warning (critical patient under 60s): pulsing alarm
- Quarantine alert (contagion detected): biohazard warning tone

ANIMATIONS:

- New casualty card slides in from the left
- Severity change: card border colour transitions smoothly
- Death: card pulses red three times, then fades to grey
- Treatment progress bar fills smoothly
- Body diagram injury regions pulse at a rate proportional to 
  urgency (critical = fast pulse, minor = slow pulse)
- Discharge: card slides out to the right with a green flash

KEYBOARD SHORTCUTS:

- Up/Down arrows: navigate casualty list
- Enter: select highlighted casualty
- A: admit selected patient
- D: discharge selected patient
- Q: quarantine selected patient
- S: stabilise worst injury on selected patient
- T: start full treatment on worst injury on selected patient
- 1-5: filter by deck number
- 0: show all decks

RESPONSIVE LAYOUT:

The two-panel layout should work on screens from 1024px to 1920px 
wide. On narrower screens, the casualty list collapses to names 
and severity badges only (no description or deck info). The body 
diagram scales to fit available space. Below 768px, switch to a 
single-column layout with a toggle between list view and detail 
view.

=============================================================
PART 5: INTEGRATION WITH EXISTING SYSTEMS
=============================================================

DAMAGE EVENTS → CASUALTIES:

Find every place in the codebase that currently creates casualties 
or crew damage. Replace the old deck-level damage with calls to 
the new injury generation system:

- game_loop_physics.py or wherever hull damage is processed:
  hull hit → generate_injuries('explosion', affected_deck, roster)

- game_loop_damage_control.py:
  fire on deck → generate_injuries('fire', deck, roster)
  hull breach → generate_injuries('hull_breach', deck, roster)
  decompression → generate_injuries('hull_breach', deck, roster)

- game_loop_security.py:
  boarding combat → generate_injuries('boarding', deck, roster)

- Environmental hazards (from v0.05h):
  radiation zone → generate_injuries('radiation', deck, roster)
  (periodic, not every tick — check every 30s while in radiation)

- Contagion mechanic (from v0.03 medical missions):
  contagion event → generate_injuries('contagion', deck, roster)

- System malfunction (sandbox events):
  malfunction → generate_injuries('system_malfunction', deck, roster)

Each integration point must:
1. Call generate_injuries with the correct cause
2. Broadcast medical.casualty to Medical client
3. Broadcast ship.casualty_report to Captain
4. Update crew factors

CAPTAIN INTEGRATION:

Captain's crew status panel (v0.04e) currently shows crew health 
by deck as colours. Update it to show:
- Total active/injured/critical/dead counts
- Worst severity currently in medical bay
- If any critical patient has death timer under 60s, flash a 
  warning: "CRITICAL PATIENT — MEDICAL BAY"
- Click a deck section to see a brief crew list for that deck 
  with status indicators

DEBRIEF INTEGRATION:

At mission end, the debrief dashboard should list:
- All casualties by name, rank, injury, and outcome (treated/died)
- Total crew lost
- Medical efficiency: average time from injury to treatment start
- Triage accuracy: were critical patients treated before minor ones?

DOCKING INTEGRATION (v0.05f):

Medical service at a friendly station:
- Transfer critical patients to station hospital (removes them 
  from the ship but heals them — they return at mission end or 
  on next dock)
- Receive replacement crew (fills dead crew positions with new 
  crew members — lower rank, generic names acceptable)
- Resupply medical supplies to 100%

SAVE/RESUME:

The entire crew roster, all injuries, all timers, all medical bay 
state, all quarantine state, and the morgue list must serialise 
and deserialise correctly. Add a round-trip test that:
1. Generates a roster
2. Injures several crew with various injuries
3. Admits some to medical bay
4. Starts treatments
5. Quarantines one
6. Kills one
7. Serialises everything
8. Clears all state
9. Deserialises
10. Verifies every value matches

=============================================================
PART 6: REMOVE OLD MEDICAL SYSTEM
=============================================================

After all new tests pass and all integration points are wired:

1. Remove the old deck-level casualty tracking code
2. Remove old Medical message handlers
3. Remove old Medical UI code
4. Update any other systems that referenced the old casualty model
5. Run full test suite — some old medical tests will need updating 
   or replacing. Every old medical test should have a corresponding 
   new test that verifies equivalent or better functionality.
6. Do NOT remove old tests until new tests cover the same ground

=============================================================
PART 7: MANUAL AND HELP OVERLAY UPDATES
=============================================================

Update the Medical section of the manual (/manual/) to describe:
- The casualty list and how to read it
- The body diagram and what the colours mean
- Treatment types and when to use each
- Triage prioritisation (treat critical first, stabilise to buy 
  time, discharge to free beds)
- Quarantine for contagion
- How crew factor works (why treating the engineer matters)
- Keyboard shortcuts

Update the Medical F1 help overlay with a condensed version.

=============================================================
AUTONOMY RULES
=============================================================

- Build in order: Part 1 → 2 → 3 → 4 → 5 → 6 → 7
- Run pytest after each part — zero regressions
- Part 1 and 2 are pure additions (no existing code changes)
- Part 3 replaces the game loop — this is the risky step. Keep 
  the old game loop until Part 3's tests all pass, then swap.
- Part 4 is a full client rewrite — no incremental migration. 
  Replace entirely.
- Part 5 is integration — touch many files carefully. Test each 
  integration point individually.
- Part 6 is cleanup — only after everything works.

STOP CONDITIONS:
- Any existing test breaks that you can't fix
- Crew factor calculation doesn't match expected values
- Injury timers aren't ticking correctly (precision issues)
- The body diagram canvas rendering is producing poor results
- You've completed all 7 parts

Full status report at each stop condition: test count, what was 
built, what was changed, known issues, decisions made.

Commit after each part with message: "v0.06.1-partN: description"

Begin with Part 1 (crew roster system) now.