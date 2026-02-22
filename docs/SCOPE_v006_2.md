Read ALL of these files before doing anything:

1. .ai/SYSTEM_PROMPT.md
2. .ai/STATE.md
3. .ai/CONVENTIONS.md
4. .ai/DECISIONS.md
5. .ai/LESSONS.md

This is v0.06.2 — a complete overhaul of the Engineering station. 
The current Engineering system has power sliders and a basic repair 
mechanic. The new system adds battery management, a repair team 
dispatch system with ship interior overlays, detailed system 
diagnostics, emergency procedures, and Security escort coordination.

Read the current Engineering implementation fully before writing 
any code:
- server/game_loop_engineering.py (or wherever engineering logic lives)
- server/engineering.py (if it exists)
- server/ship.py (power budget, system health, efficiency calc)
- client/engineering/engineering.js
- client/engineering/engineering.css
- client/engineering/index.html
- Any test files: tests/test_engineering*.py, tests/test_game_loop_engineering*.py

Also read the v0.06.1 crew roster implementation — Engineering's 
repair teams are drawn from the crew roster. Understand how 
crew_factor_for_system works and how the crew roster integrates 
with ship systems.

Understand how Engineering currently works — what messages it sends 
and receives, how power allocation works, how repair works, how the 
schematic displays, and how efficiency is calculated. The new system 
wraps around and extends all of this.

=============================================================
PART 1: POWER GRID MODEL (server/models/power_grid.py — new file)
=============================================================

The current power system is sliders that set percentages. The new 
system adds a proper power grid with generation, storage, routing, 
and consumption.

POWER GRID MODEL:

@dataclass
class PowerGrid:
    # Generation
    reactor_output: float          # Base power generation per tick
    reactor_health: float          # 0-100%, affects output
    reactor_max: float             # Maximum possible output
    
    # Storage
    battery_capacity: float        # Maximum stored energy (MJ)
    battery_charge: float          # Current stored energy (MJ)
    battery_charge_rate: float     # Max MJ per second input
    battery_discharge_rate: float  # Max MJ per second output
    battery_mode: str              # "charging", "discharging", "standby", "auto"
    
    # Emergency
    emergency_power: bool          # Emergency reserves active
    emergency_reserve: float       # Small reserve (20% of capacity)
    emergency_duration: float      # Seconds of emergency power remaining
    
    # Distribution
    allocations: dict[str, float]  # system_name → power % (existing)
    overrides: dict[str, bool]     # Captain overrides (existing)
    bus_routes: dict[str, str]     # system → bus ("primary", "secondary")

REACTOR:

The reactor generates power continuously. reactor_output = 
reactor_max × (reactor_health / 100). When the reactor takes 
damage, output drops. If reactor_health reaches 0, the ship goes 
dark — emergency power kicks in automatically (if available).

Reactor health is repaired by Engineering repair teams (not the 
power slider — you can't slide your way out of a damaged reactor). 
The reactor is a repairable system like any other, but it's the 
most critical one.

Ship class JSON should define reactor stats:

"power_grid": {
    "reactor_max": 700,
    "battery_capacity": 500,
    "battery_charge_rate": 50,
    "battery_discharge_rate": 100,
    "emergency_reserve": 100
}

BATTERY SYSTEM:

Batteries store excess power and discharge it when needed. This 
creates a new tactical dimension — Engineering can overcharge 
systems briefly by discharging batteries, or save power during 
quiet moments for a combat burst later.

Battery modes:
- "charging": Excess power (generation minus consumption) charges 
  the battery. If generation < consumption, battery doesn't 
  discharge — systems get reduced power.
- "discharging": Battery supplements reactor output. Total 
  available power = reactor_output + battery_discharge_rate. 
  Drains battery_charge over time.
- "standby": Battery neither charges nor discharges. Holds current 
  charge.
- "auto": Smart mode — charges when surplus exists, discharges 
  when demand exceeds generation. Default mode.

The power budget display changes from a static number to a dynamic 
equation:

  Available = Reactor Output ± Battery Flow
  Consumed  = Sum of all system allocations
  Surplus/Deficit = Available - Consumed

When in deficit, all systems receive proportionally reduced power 
(brownout). When in surplus and battery mode is "auto" or 
"charging", excess flows to batteries.

EMERGENCY POWER:

When reactor_output drops to 0 (reactor destroyed or offline):
- Emergency reserves activate automatically
- Provides emergency_reserve power (20% of normal)
- Lasts emergency_duration seconds (calculated from reserve / consumption)
- Engineering gets urgent alert: "EMERGENCY POWER — REACTOR OFFLINE"
- Only essential systems get power (Engineering prioritises)
- When emergency reserve depletes: total blackout. Shields drop, 
  sensors go dark, weapons offline. Helm retains minimal 
  manoeuvring only (mechanical backup).
- This creates a hard countdown: fix the reactor or lose everything

POWER BUS ROUTING:

Systems are connected to one of two power buses:

- Primary bus: engines, shields, sensors, manoeuvring (critical)
- Secondary bus: weapons, flight deck, ECM, point defence (combat)

If one bus is damaged (by targeted enemy fire or system malfunction), 
all systems on that bus lose power. Engineering can reroute systems 
between buses:

  engineering.reroute_system { system: str, bus: "primary"|"secondary" }

Rerouting takes 10 seconds (physical relay switching). During 
reroute, the system is offline. This creates emergency decisions: 
primary bus is hit, do you reroute shields to secondary (10s without 
shields) or try to repair the bus (longer but keeps shields up 
during repair)?

Bus damage is a new damage type that enemies can inflict (targeted 
system attacks) or that occurs from internal explosions.

TESTS: Write tests/test_power_grid.py
- Reactor output scales with health
- Battery charges when surplus exists
- Battery discharges when deficit exists
- Auto mode switches correctly
- Emergency power activates when reactor goes offline
- Emergency reserve depletes over time
- Power bus routing works
- Reroute takes 10 seconds
- Bus damage cuts power to all systems on that bus
- Brownout distributes reduced power proportionally
- Serialise/deserialise round-trip
Target: 35+ tests

=============================================================
PART 2: REPAIR TEAM SYSTEM (server/models/repair_teams.py — new)
=============================================================

Currently repair is a single abstract mechanic. The new system has 
named repair teams drawn from the crew roster that physically move 
through the ship to reach damaged systems.

REPAIR TEAM MODEL:

@dataclass
class RepairTeam:
    id: str                      # "rt_alpha", "rt_beta", etc.
    name: str                    # "Alpha Team", "Beta Team", etc.
    members: list[str]           # crew_member_ids from roster
    leader: str                  # crew_member_id of team leader
    size: int                    # Number of members (3-5)
    location: str                # Current deck/room: "deck_3", "reactor"
    destination: str | None      # Where they're heading
    status: str                  # "idle", "en_route", "repairing", 
                                 # "returning", "incapacitated"
    travel_progress: float       # 0-1.0 progress to destination
    repair_progress: float       # 0-1.0 progress on current repair
    repair_target: str | None    # System being repaired
    escorted: bool               # Security escort assigned
    escort_requested: bool       # Waiting for Security escort
    
    @property
    def effectiveness(self) -> float:
        """Team repair speed multiplier based on size and member health."""
        # Full team of 4 healthy crew = 1.0
        # Injured members contribute less
        # Fewer members = slower repairs
        ...

REPAIR TEAM GENERATION:

At game start, create repair teams from the Engineering crew in 
the crew roster. Ship class determines team count:

| Ship Class | Repair Teams | Team Size |
|-----------|-------------|-----------|
| Scout | 1 | 3 |
| Corvette | 2 | 3 |
| Frigate | 2 | 4 |
| Cruiser | 3 | 4 |
| Battleship | 4 | 4 |
| Medical Ship | 2 | 3 |
| Carrier | 3 | 4 |

Team members are drawn from crew assigned to the Engineering duty 
station. Each team gets a leader (highest rank). Teams start in 
the engineering section (Deck 3 typically).

REPAIR DISPATCH:

Engineering selects a damaged system and dispatches a repair team:

  engineering.dispatch_repair { team_id: str, target_system: str }

The flow:
1. Team status → "en_route"
2. Team travels from current location to the target system's deck
   Travel time = deck_distance × travel_speed
   (Adjacent decks = 5s, 2 decks away = 10s, etc.)
3. If the area is hazardous (fire, breach, radiation, intruders), 
   the team STOPS and requests a Security escort:
   - Team status → "awaiting_escort"
   - Notification sent to Security: "Engineering team Alpha requests 
     escort to Deck 3 — active fire"
   - Team waits until Security assigns an escort OR Engineering 
     forces them to proceed without escort (risky — team members 
     may be injured by the hazard)
4. Team arrives, status → "repairing"
5. Repair progress ticks upward: repair_speed × effectiveness × tick
   Base repair_speed: 2% per second (50s for a full repair)
   Effectiveness multiplier from team health and size
6. On completion: system health restored, team status → "idle"
7. Team returns to engineering section (auto, no dispatch needed)

MULTIPLE REPAIRS:

Multiple teams can repair different systems simultaneously. A single 
team can only repair one system at a time. If the ship has 3 teams, 
Engineering can repair 3 systems at once.

Two teams CAN be assigned to the same system for faster repair:
combined_speed = team1.effectiveness + team2.effectiveness × 0.7
(diminishing returns — two teams aren't twice as fast due to 
coordination overhead)

REPAIR PRIORITY QUEUE:

Engineering can set a priority queue of repairs:

  engineering.set_repair_queue { priorities: [system_name, ...] }

When a team finishes a repair and goes idle, it automatically picks 
up the next item in the priority queue. This means Engineering sets 
the strategy ("fix shields first, then engines, then weapons") and 
teams execute it automatically, freeing Engineering to focus on 
power management.

TEAM CASUALTIES:

If a repair team is in an area that takes damage (explosion, fire, 
breach), team MEMBERS can be injured (using the v0.06.1 injury 
system). Injured team members reduce the team's effectiveness. If 
the team leader is incapacitated, effectiveness drops 25% (no 
coordinator). If all members are down, the team is "incapacitated" 
and cannot repair until Medical treats them.

Injured team members are added to the Medical casualty list just 
like any other crew. Medical sees "PO Chen — Alpha Team — compound 
fracture, Deck 3" and knows that treating Chen gets a repair team 
back to strength.

This creates Engineering ↔ Medical interdependency: Engineering 
needs their repair teams healthy, Medical needs Engineering to 
repair the medical bay systems.

SECURITY ESCORT MECHANIC:

When a repair team encounters a hazard at their destination:

1. Team stops and sets escort_requested = True
2. Server sends notification to Security:
   engineering.escort_request {
       team_id: "rt_alpha",
       team_name: "Alpha Team", 
       destination: "deck_3",
       hazard: "fire"  // or "intruders", "breach", "radiation"
   }
3. Security player sees the request on their interior map — the 
   repair team icon appears with an escort request marker
4. Security assigns a marine team to escort:
   security.assign_escort { 
       marine_team_id: str, 
       engineering_team_id: str 
   }
5. Marine team travels to the repair team's location
6. When marines arrive, the repair team proceeds with escort
7. If hazard is intruders: marines engage while repair team works
   If hazard is fire/breach: marines provide no benefit but the 
   team proceeds (Engineering chose to send them in)
   If hazard is radiation: escort doesn't help — Engineering must 
   decide to send the team in anyway (they'll take radiation 
   injuries) or wait until the radiation clears

If Engineering forces the team to proceed without escort:
  engineering.force_proceed { team_id: str }
  — Team enters hazardous area
  — Each team member rolls for injury based on hazard type
  — Repairs proceed but team may take casualties

TESTS: Write tests/test_repair_teams.py
- Team generation from crew roster
- Team dispatch and travel time calculation
- Repair progress ticks correctly
- Effectiveness scales with team health/size
- Leader incapacitation penalty
- Two teams on same system (diminishing returns)
- Priority queue auto-dispatch
- Hazard detection stops team
- Escort request sent to Security
- Force proceed causes injuries
- Team casualties integrate with crew roster
- Serialise/deserialise round-trip
Target: 40+ tests

=============================================================
PART 3: DAMAGE DIAGNOSTIC SYSTEM (server/models/damage_model.py)
=============================================================

Currently damage is a single health percentage per system. The new 
system tracks WHERE damage occurred and WHAT kind of damage it is.

SYSTEM DAMAGE MODEL:

@dataclass
class SystemDamage:
    system_name: str
    health: float                 # 0-100% (existing)
    damage_events: list[DamageEvent]  # History of damage
    components: dict[str, ComponentState]  # Sub-components

@dataclass 
class DamageEvent:
    id: str
    tick: int
    cause: str                    # "beam_hit", "torpedo_hit", 
                                  # "internal_explosion", "fire", 
                                  # "boarding_sabotage", "collision"
    severity: float               # Damage amount
    deck: int                     # Where the damage occurred
    description: str              # "Torpedo impact — forward shield 
                                  #  generator housing buckled"
    repaired: bool

@dataclass
class ComponentState:
    name: str                     # "power_coupling", "coolant_line",
                                  # "control_circuit", "structural"
    health: float                 # 0-100%
    critical: bool                # Is this a critical component?
    effect_when_damaged: str       # What happens when this fails

SYSTEM COMPONENTS:

Each ship system has 3-4 sub-components that can be damaged 
independently. When a system takes damage, one or more components 
are affected. The system's overall health is the weighted average 
of its components. Critical components have higher weight.

Engines:
- Reactor core (critical) — damage reduces power output
- Coolant system — damage causes overheating (efficiency loss over time)
- Drive assembly — damage reduces max speed
- Fuel lines — damage causes fuel leak (gradual fuel loss)

Shields:
- Generator coils (critical) — damage reduces max shield strength
- Emitter array — damage creates gaps in coverage
- Power coupling — damage causes intermittent shield flicker
- Control circuits — damage makes shield focus less responsive

Weapons (beams):
- Beam emitters (critical) — damage reduces damage output
- Targeting array — damage reduces accuracy
- Power coupling — damage causes intermittent beam cutouts
- Cooling system — damage causes overheat (forced cooldown pauses)

Weapons (torpedoes):
- Loading mechanism (critical) — damage increases reload time
- Launch tubes — damage may jam (tube unusable until repaired)
- Magazine — damage risks cook-off (explosion, very dangerous)
- Guidance system — damage reduces torpedo accuracy

Sensors:
- Main array (critical) — damage reduces scan range
- Signal processor — damage increases scan time
- Calibration unit — damage reduces scan accuracy
- Power coupling — damage causes intermittent sensor dropouts

Manoeuvring:
- Thruster array (critical) — damage reduces turn rate
- Control linkage — damage causes input lag
- Stabiliser — damage causes drift (ship slowly rotates off heading)
- RCS fuel — damage causes fuel leak

Flight deck:
- Launch catapult (critical) — damage prevents drone launch
- Recovery system — damage prevents drone recovery
- Fuel lines — damage prevents drone refuelling
- Control tower — damage reduces drone command range

ECM suite:
- Jammer array (critical) — damage reduces jam effectiveness
- Signal processor — damage increases countermeasure response time
- Antenna array — damage reduces jam range
- Power coupling — damage causes intermittent dropouts

Point defence:
- Tracking radar (critical) — damage reduces intercept chance
- Gun assembly — damage reduces fire rate
- Ammo feed — damage causes jams (temporary offline)
- Targeting computer — damage causes friendly fire risk (very rare)

When a system takes damage, the game rolls to determine which 
component(s) are affected. Critical components are less likely to 
be hit (better protected) but more impactful when they are. 
Component damage causes the specific effect listed — this replaces 
the generic "system at 60% = 60% effectiveness" with nuanced 
degradation.

Example: Shields at 75% health could mean:
- Generator coils at 50% (max shield strength reduced to 75%) OR
- Emitter array at 0% (full strength but coverage gaps) OR  
- Power coupling at 25% (shields flicker on and off randomly)

Each scenario plays differently even at the same health percentage. 
Engineering sees the component breakdown and can explain to the crew 
what's actually wrong: "Shields are flickering because the power 
coupling is shot — I'm sending Beta Team to fix it."

DAMAGE GENERATION:

When a system takes damage (from any source), replace the simple 
"reduce health by X" with:

1. Determine which component(s) are hit (weighted random, critical 
   components less likely)
2. Apply damage to component health
3. Recalculate system overall health from component weighted average
4. Create a DamageEvent record with description
5. Apply the component's specific effect
6. Broadcast detailed damage to Engineering client:
   engineering.damage_report {
       system: "shields",
       component: "power_coupling",
       component_health: 25.0,
       system_health: 75.0,
       effect: "Intermittent shield flicker",
       description: "Torpedo impact — shield power coupling damaged",
       deck: 2,
       event_id: "dmg_042"
   }

TESTS: Write tests/test_damage_model.py
- System components initialise correctly
- Damage distributes to components
- System health recalculates from components
- Component effects apply correctly
- Critical component weighting works
- DamageEvent history records correctly
- Specific effects trigger (e.g., coolant damage causes overheat)
- Serialise/deserialise round-trip
Target: 35+ tests

=============================================================
PART 4: ENGINEERING GAME LOOP (server/game_loop_engineering.py — rewrite)
=============================================================

Replace the existing engineering game loop with one that manages 
the power grid, repair teams, and damage diagnostics.

TICK PROCESSING:

def tick(ship, power_grid, repair_teams, damage_model, game_state):
    actions = []
    
    # 1. Reactor output (affected by health)
    actual_output = power_grid.reactor_max * (power_grid.reactor_health / 100)
    
    # 2. Battery management
    total_consumption = sum(allocations × system demands)
    surplus = actual_output - total_consumption
    
    if power_grid.battery_mode == 'auto':
        if surplus > 0:
            charge = min(surplus, power_grid.battery_charge_rate) * dt
            power_grid.battery_charge = min(
                power_grid.battery_charge + charge,
                power_grid.battery_capacity
            )
        elif surplus < 0:
            discharge = min(-surplus, power_grid.battery_discharge_rate) * dt
            discharge = min(discharge, power_grid.battery_charge)
            power_grid.battery_charge -= discharge
            surplus += discharge
    
    # 3. If still in deficit → brownout
    if surplus < 0:
        brownout_factor = actual_output / total_consumption
        apply_brownout(ship, brownout_factor)
        actions.append(brownout_warning(brownout_factor))
    
    # 4. Emergency power check
    if actual_output == 0 and not power_grid.emergency_power:
        activate_emergency_power(power_grid)
        actions.append(emergency_power_alert())
    if power_grid.emergency_power:
        power_grid.emergency_duration -= dt
        if power_grid.emergency_duration <= 0:
            total_blackout(ship)
            actions.append(blackout_alert())
    
    # 5. Tick repair teams
    for team in repair_teams:
        if team.status == 'en_route':
            team.travel_progress += travel_speed * dt
            if team.travel_progress >= 1.0:
                if hazard_at_destination(team.destination, game_state):
                    team.status = 'awaiting_escort'
                    team.escort_requested = True
                    actions.append(escort_request(team))
                else:
                    team.status = 'repairing'
                    actions.append(repair_started(team))
        
        elif team.status == 'repairing':
            progress = repair_speed * team.effectiveness * dt
            team.repair_progress += progress
            if team.repair_progress >= 1.0:
                complete_repair(team, damage_model)
                actions.append(repair_complete(team))
                # Auto-pick next from priority queue
                next_target = get_next_priority(repair_queue)
                if next_target:
                    dispatch_team(team, next_target)
                else:
                    team.status = 'returning'
    
    # 6. Tick component effects
    for system_name, system_damage in damage_model.items():
        for comp_name, comp in system_damage.components.items():
            if comp.health < 100:
                apply_component_effect(comp, ship, game_state, dt)
    
    # 7. Tick bus health
    if power_grid.primary_bus_health <= 0:
        for system in primary_bus_systems:
            ship.set_system_power(system, 0)
    
    # 8. Broadcast state
    actions.append(engineering_state_broadcast(power_grid, 
        repair_teams, damage_model))
    
    return actions

MESSAGE HANDLERS:

engineering.set_power { system: str, level: float }
  — Existing behaviour, but now checked against available power
    (reactor + battery). If total allocation exceeds available, 
    warn the player but allow it (causes brownout).

engineering.set_battery_mode { mode: str }
  — Set battery to "charging", "discharging", "standby", or "auto"

engineering.dispatch_repair { team_id: str, target_system: str }
  — Send a repair team to fix a system. If the system has multiple
    damaged components, the team repairs the most critical first.

engineering.set_repair_queue { priorities: [str, ...] }
  — Set the auto-repair priority list.

engineering.force_proceed { team_id: str }
  — Force a repair team to enter a hazardous area without escort.

engineering.recall_team { team_id: str }
  — Recall a repair team to engineering section. Cancels current 
    repair (progress is saved — team can resume later).

engineering.reroute_system { system: str, bus: str }
  — Move a system from one power bus to another. 10-second offline 
    period during reroute.

engineering.activate_emergency_power {}
  — Manually activate emergency reserves (normally auto, but 
    Engineering can trigger it early to get extra power briefly).

engineering.request_escort { team_id: str }
  — Explicitly request Security escort for a team (rather than 
    waiting for the auto-request when team hits a hazard).

TESTS: Write tests/test_game_loop_engineering_v2.py
- Power allocation with reactor output
- Battery charge/discharge in all modes
- Brownout calculation and application
- Emergency power activation and depletion
- Blackout when emergency depletes
- Repair team dispatch and travel
- Repair progress and completion
- Priority queue auto-dispatch
- Force proceed injury generation
- Escort request flow
- Team recall and resume
- Bus reroute with offline period
- Bus damage cuts system power
- Component effect application per tick
- Serialise/deserialise round-trip
Target: 50+ tests

=============================================================
PART 5: ENGINEERING CLIENT UI (client/engineering/ — full rewrite)
=============================================================

Complete overhaul. The Engineering station becomes the ship's 
nerve centre — power management, damage diagnostics, repair team 
command, and system monitoring.

LAYOUT:

┌──────────────────────┬──────────────────────┬───────────────┐
│ POWER MANAGEMENT     │ SHIP INTERIOR MAP    │ SYSTEM DETAIL │
│                      │ [overlay selector]   │               │
│ Reactor: ████ 85%    │                      │ SHIELDS       │
│ Output: 595/700      │ ┌──────────────────┐ │ Health: 75%   │
│                      │ │                  │ │               │
│ Battery: ████░ 62%   │ │  Ship cutaway    │ │ Components:   │
│ Mode: [AUTO]         │ │  with damage     │ │ ▶ Gen coils   │
│ Flow: +12 MJ/s      │ │  overlays and    │ │   ████░ 80%   │
│                      │ │  repair team     │ │ ▶ Emitters    │
│ Available: 607 MJ/s  │ │  positions       │ │   ██████ 100% │
│ Consumed:  580 MJ/s  │ │                  │ │ ▶ Pwr coupling│
│ Surplus:   +27 MJ/s  │ │  [RT-α] →[deck3] │ │   █░░░░ 25%  │
│                      │ │  [RT-β] idle     │ │   ⚠ FLICKERING│
│ POWER ALLOCATION     │ └──────────────────┘ │ ▶ Ctrl circuit│
│                      │                      │   ██████ 100% │
│ Engines    ████████  │ REPAIR TEAMS         │               │
│            80% [──]  │                      │ Effect:       │
│ Beams      ██████████│ α Alpha — REPAIRING  │ Shield power  │
│            100% [──] │   Shields / Deck 2   │ coupling at   │
│ Torpedoes  ██████    │   Progress: ████░ 78%│ 25% — causing │
│            60% [──]  │                      │ intermittent  │
│ Shields    ████████  │ β Beta — IDLE        │ shield flicker│
│            80% [──]  │   Engineering        │ every 3-5 sec │
│ Sensors    ████████  │   [DISPATCH ▼]       │               │
│            80% [──]  │                      │ [DISPATCH α]  │
│ Manoeuvring████████  │ γ Gamma — EN ROUTE   │ [DISPATCH β]  │
│            80% [──]  │   → Engines / Deck 3 │               │
│ Flight Deck██████    │   ETA: 4s            │ DAMAGE LOG:   │
│            60% [──]  │                      │ 03:42 Torpedo  │
│ ECM        ████      │ ESCORT REQUESTS:     │  impact — pwr │
│            40% [──]  │ ⚠ Gamma needs escort │  coupling dmg │
│ Point Def  ██████    │   to Deck 3 (FIRE)   │ 02:15 Beam    │
│            60% [──]  │   [REQUEST] [FORCE]  │  hit — gen    │
│                      │                      │  coil stress  │
│ REPAIR QUEUE:        │                      │               │
│ 1. Shields           │ BUS STATUS:          │               │
│ 2. Engines           │ Primary:  ████ 90%   │               │
│ 3. Weapons           │ Secondary:██████ 100%│               │
│ [EDIT QUEUE]         │ [REROUTE...]         │               │
├──────────────────────┴──────────────────────┴───────────────┤
│ ⚡ POWER OK │ 🔋 BAT 62% AUTO │ 🔧 2/3 TEAMS ACTIVE │     │
│ BUS: PRI ✓ SEC ✓ │ EMERGENCY: READY │ SUPPLIES: 85%      │
└─────────────────────────────────────────────────────────────┘