# STARBRIDGE v0.07 — SHIP CLASS OVERHAUL
## Complete Specification & Audit Checklist

**Version:** 1.0
**Date:** February 2026
**Author:** Peter Howse / Claude
**Status:** Specification

---

## OVERVIEW

v0.07 transforms ship classes from cosmetic labels into fundamentally different gameplay experiences. Each ship class should make different stations important, create different tactical challenges, and require different crew strategies.

**Design Principle:** Each ship class answers the question "What is this crew good at, what are they bad at, and what can they do that nobody else can?"

**Build Phases:**
- Phase 1: Ship stat differentiation (data + balance)
- Phase 2: Unique ship systems (new mechanics per class)
- Phase 3: Pre-mission loadout configuration (lobby UI)
- Phase 4: Visual identity (wireframes, silhouettes, interior layouts)
- Phase 5: Integration and balance testing

---

## PHASE 1: SHIP STAT DIFFERENTIATION

### 1.1 Physical Profiles

Every ship class must have dramatically different physical characteristics. "Dramatically" means the crew FEELS the difference — not 10% variation, but 2-3x variation between extremes.

#### 1.1.1 Scout

The scout is a glass cannon racer. Fast, agile, fragile. Helm is the star station — survival depends on not getting hit.

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.1.1.1 Hull points | 60 | |
| [ ] 1.1.1.2 Max speed | 250 units/s | |
| [ ] 1.1.1.3 Acceleration | 50 units/s² (0 to max in 5s) | |
| [ ] 1.1.1.4 Turn rate | 180°/s (can reverse heading in 1s) | |
| [ ] 1.1.1.5 Target profile | 0.5 (small, hard to hit at range) | |
| [ ] 1.1.1.6 Armour | 0 (no armour, all damage passes through) | |
| [ ] 1.1.1.7 Crew complement | 8-12 | |
| [ ] 1.1.1.8 Decks | 3 (compact) | |
| [ ] 1.1.1.9 Handling trait | "Twitchy" — oversensitive to helm input, small corrections cause overshoot. Turn rate is high but stopping a turn requires counter-input. Helm must learn finesse. | |

#### 1.1.2 Corvette

The corvette is the intelligence/EW platform. Moderate in combat, exceptional in electronic warfare and stealth. EW and Comms are the star stations.

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.1.2.1 Hull points | 90 | |
| [ ] 1.1.2.2 Max speed | 200 units/s | |
| [ ] 1.1.2.3 Acceleration | 40 units/s² | |
| [ ] 1.1.2.4 Turn rate | 120°/s | |
| [ ] 1.1.2.5 Target profile | 0.6 | |
| [ ] 1.1.2.6 Armour | 5 (light armour, absorbs minor hits) | |
| [ ] 1.1.2.7 Crew complement | 14-18 | |
| [ ] 1.1.2.8 Decks | 4 | |
| [ ] 1.1.2.9 Handling trait | "Smooth" — responsive controls, no quirks. The baseline ship that all others are compared against. Easy to fly, nothing exceptional. | |

#### 1.1.3 Frigate

The frigate is the all-rounder. Balanced in everything, dominant in nothing. The crew that coordinates best wins. Good classroom default.

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.1.3.1 Hull points | 120 | |
| [ ] 1.1.3.2 Max speed | 160 units/s | |
| [ ] 1.1.3.3 Acceleration | 30 units/s² | |
| [ ] 1.1.3.4 Turn rate | 90°/s | |
| [ ] 1.1.3.5 Target profile | 0.75 | |
| [ ] 1.1.3.6 Armour | 10 | |
| [ ] 1.1.3.7 Crew complement | 18-24 | |
| [ ] 1.1.3.8 Decks | 5 | |
| [ ] 1.1.3.9 Handling trait | "Clean" — precise, predictable. What you input is what you get. No surprises. The pilot training ship. | |

#### 1.1.4 Cruiser

The cruiser is the command ship. Strong across the board with enhanced tactical capabilities. Captain and Tactical are the star stations.

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.1.4.1 Hull points | 180 | |
| [ ] 1.1.4.2 Max speed | 120 units/s | |
| [ ] 1.1.4.3 Acceleration | 20 units/s² | |
| [ ] 1.1.4.4 Turn rate | 60°/s | |
| [ ] 1.1.4.5 Target profile | 0.85 | |
| [ ] 1.1.4.6 Armour | 20 | |
| [ ] 1.1.4.7 Crew complement | 30-40 | |
| [ ] 1.1.4.8 Decks | 6 | |
| [ ] 1.1.4.9 Handling trait | "Steady" — moderate input lag (0.3s), but once turning the ship holds heading precisely. Doesn't drift, doesn't overshoot. Reliable and predictable at the cost of responsiveness. | |

#### 1.1.5 Battleship

The battleship is the fortress. Enormous hull, devastating weapons, glacially slow. Engineering and Weapons are the star stations. Every system is powerful but draws massive power.

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.1.5.1 Hull points | 300 | |
| [ ] 1.1.5.2 Max speed | 80 units/s | |
| [ ] 1.1.5.3 Acceleration | 10 units/s² (0 to max in 8s) | |
| [ ] 1.1.5.4 Turn rate | 30°/s (6 seconds to turn 180°) | |
| [ ] 1.1.5.5 Target profile | 1.0 (massive, everything hits) | |
| [ ] 1.1.5.6 Armour | 40 (separate armour layer, see 2.5.2) | |
| [ ] 1.1.5.7 Crew complement | 50-65 | |
| [ ] 1.1.5.8 Decks | 8 | |
| [ ] 1.1.5.9 Handling trait | "Ponderous" — 0.5s input lag on all helm controls. Ship accelerates and decelerates slowly. Once moving, significant momentum — cannot stop quickly. Helm must plan 10-15 seconds ahead. Turning at speed causes slight drift (ship slides sideways during turn before settling on new heading). | |

#### 1.1.6 Carrier

The carrier is the drone platform. Minimal direct weapons, massive flight ops capability. Flight Ops is the star station — the carrier's combat power IS its drones.

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.1.6.1 Hull points | 200 | |
| [ ] 1.1.6.2 Max speed | 100 units/s | |
| [ ] 1.1.6.3 Acceleration | 15 units/s² | |
| [ ] 1.1.6.4 Turn rate | 45°/s | |
| [ ] 1.1.6.5 Target profile | 0.95 (huge flight deck) | |
| [ ] 1.1.6.6 Armour | 15 | |
| [ ] 1.1.6.7 Crew complement | 40-55 | |
| [ ] 1.1.6.8 Decks | 7 (including 2 hangar decks) | |
| [ ] 1.1.6.9 Handling trait | "Heavy" — similar to battleship but slightly more responsive. Pronounced lateral drift when changing heading due to asymmetric mass (flight deck on one side). Helm learns to compensate. | |

#### 1.1.7 Medical Ship

The medical ship is the support vessel. No offensive weapons, exceptional medical and rescue capability. Medical is the star station. Comms and diplomacy are critical because you can't fight your way out.

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.1.7.1 Hull points | 100 | |
| [ ] 1.1.7.2 Max speed | 140 units/s | |
| [ ] 1.1.7.3 Acceleration | 25 units/s² | |
| [ ] 1.1.7.4 Turn rate | 75°/s | |
| [ ] 1.1.7.5 Target profile | 0.7 | |
| [ ] 1.1.7.6 Armour | 5 | |
| [ ] 1.1.7.7 Crew complement | 20-30 (heavy on medical staff) | |
| [ ] 1.1.7.8 Decks | 5 (2 dedicated medical decks) | |
| [ ] 1.1.7.9 Handling trait | "Gentle" — smooth, responsive, forgiving. Easy to fly. The ship is designed for non-combat crew to operate comfortably. No quirks, no surprises, no drama. | |

### 1.2 Target Profile Mechanic

[ ] 1.2.1 Target profile is a new stat that affects hit probability for incoming fire.

[ ] 1.2.2 When an enemy fires at the player ship, hit chance = base_accuracy × target_profile. A scout with 0.5 profile is hit half as often as a battleship with 1.0 profile.

[ ] 1.2.3 Target profile is also affected by speed. A moving ship is harder to hit than a stationary one: effective_profile = base_profile × (1.0 - speed_factor × 0.3). A scout at full speed: 0.5 × (1.0 - 1.0 × 0.3) = 0.35. Very hard to hit. A stationary battleship: 1.0 × 1.0 = 1.0. Everything hits.

[ ] 1.2.4 This creates a Helm ↔ survival dependency. On a scout, Helm MUST keep moving or the ship dies. On a battleship, movement barely matters for defence — shields and armour are the defence.

[ ] 1.2.5 Target profile applies when the player ship fires at enemy ships too. Larger enemy ships are easier to hit. Weapons accuracy against a target = base_accuracy × target.profile.

### 1.3 Armour System

[ ] 1.3.1 Armour is a damage reduction layer that sits between shields and hull. After shields absorb what they can, remaining damage hits armour. Armour absorbs damage equal to its value per hit. Damage that exceeds armour passes through to hull. Example: 15 damage hits, armour value is 10, hull takes 5 damage.

[ ] 1.3.2 Armour degrades. Each hit that armour absorbs reduces armour value by 1. A battleship starts at 40 armour, but after 40 hits the armour is stripped and all damage passes through.

[ ] 1.3.3 Armour can be repaired by Engineering repair teams but only to 75% of original value in the field. Full repair requires docking.

[ ] 1.3.4 Armour is NOT affected by power allocation — it's physical plating, not a powered system.

[ ] 1.3.5 Engineering UI shows armour as a separate bar between shields and hull: SHIELDS → ARMOUR → HULL.

[ ] 1.3.6 Captain's damage display shows armour status.

[ ] 1.3.7 Armour value is defined per ship class in the ship class JSON.

### 1.4 Power Grid Per Ship Class

Each ship class has a distinctive power grid that forces different Engineering tradeoffs.

#### 1.4.1 Scout Power Grid

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.4.1.1 Reactor max output | 300 MJ/s | |
| [ ] 1.4.1.2 Battery capacity | 150 MJ | |
| [ ] 1.4.1.3 Battery charge rate | 30 MJ/s | |
| [ ] 1.4.1.4 Battery discharge rate | 60 MJ/s | |
| [ ] 1.4.1.5 Emergency reserve | 60 MJ | |
| [ ] 1.4.1.6 Power personality | Tiny reactor, tiny battery. Can run engines OR shields OR weapons at full, but not all three. Every power decision is a sacrifice. Battery gives one 30-second combat burst. Engineering is constantly making hard choices. | |

#### 1.4.2 Corvette Power Grid

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.4.2.1 Reactor max output | 450 MJ/s | |
| [ ] 1.4.2.2 Battery capacity | 250 MJ | |
| [ ] 1.4.2.3 Battery charge rate | 40 MJ/s | |
| [ ] 1.4.2.4 Battery discharge rate | 80 MJ/s | |
| [ ] 1.4.2.5 Emergency reserve | 80 MJ | |
| [ ] 1.4.2.6 Power personality | Moderate reactor. ECM systems are uniquely efficient (consume 60% of normal power cost). This means the corvette can run powerful ECM while maintaining other systems. Other ships running ECM at full would brownout; the corvette handles it comfortably. | |
| [ ] 1.4.2.7 ECM power efficiency | 0.6 multiplier on ECM power consumption | |

#### 1.4.3 Frigate Power Grid

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.4.3.1 Reactor max output | 700 MJ/s | |
| [ ] 1.4.3.2 Battery capacity | 500 MJ | |
| [ ] 1.4.3.3 Battery charge rate | 50 MJ/s | |
| [ ] 1.4.3.4 Battery discharge rate | 100 MJ/s | |
| [ ] 1.4.3.5 Emergency reserve | 100 MJ | |
| [ ] 1.4.3.6 Power personality | Balanced. Can run most systems simultaneously at 70-80%. Full power to everything causes a slight deficit that battery covers. The comfortable ship. | |

#### 1.4.4 Cruiser Power Grid

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.4.4.1 Reactor max output | 1000 MJ/s | |
| [ ] 1.4.4.2 Battery capacity | 750 MJ | |
| [ ] 1.4.4.3 Battery charge rate | 70 MJ/s | |
| [ ] 1.4.4.4 Battery discharge rate | 140 MJ/s | |
| [ ] 1.4.4.5 Emergency reserve | 150 MJ | |
| [ ] 1.4.4.6 Power personality | Strong reactor, strong battery. Can sustain most systems at 80-90%. The dual beam arrays draw significant power when both active. Engineering has breathing room but can't be wasteful. | |

#### 1.4.5 Battleship Power Grid

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.4.5.1 Reactor max output | 1500 MJ/s | |
| [ ] 1.4.5.2 Battery capacity | 1200 MJ | |
| [ ] 1.4.5.3 Battery charge rate | 100 MJ/s | |
| [ ] 1.4.5.4 Battery discharge rate | 200 MJ/s | |
| [ ] 1.4.5.5 Emergency reserve | 250 MJ | |
| [ ] 1.4.5.6 Power personality | Massive reactor, massive battery, massive consumption. The spinal mount weapon alone draws 40% of reactor output during charge. Heavy beams, layered shields, and full systems consume everything. Engineering is ALWAYS busy managing power priorities. When the spinal mount charges, something else must power down. | |
| [ ] 1.4.5.7 Spinal mount power draw | 600 MJ/s during 30s charge (40% of reactor) | |

#### 1.4.6 Carrier Power Grid

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.4.6.1 Reactor max output | 900 MJ/s | |
| [ ] 1.4.6.2 Battery capacity | 800 MJ | |
| [ ] 1.4.6.3 Battery charge rate | 80 MJ/s | |
| [ ] 1.4.6.4 Battery discharge rate | 120 MJ/s | |
| [ ] 1.4.6.5 Emergency reserve | 120 MJ | |
| [ ] 1.4.6.6 Power personality | Good reactor but the flight deck is a constant 15% passive drain (catapult standby, recovery systems, hangar environmental). When actively launching/recovering, flight deck surges to 25%. Engineering must balance flight ops against other systems. Weapons draw is low (minimal armament) so the tradeoff is usually flight deck vs shields. | |
| [ ] 1.4.6.7 Flight deck passive power draw | 15% of reactor (135 MJ/s) | |
| [ ] 1.4.6.8 Flight deck active power draw | 25% of reactor (225 MJ/s) during launch/recovery | |

#### 1.4.7 Medical Ship Power Grid

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.4.7.1 Reactor max output | 500 MJ/s | |
| [ ] 1.4.7.2 Battery capacity | 600 MJ (oversized for emergencies) | |
| [ ] 1.4.7.3 Battery charge rate | 50 MJ/s | |
| [ ] 1.4.7.4 Battery discharge rate | 100 MJ/s | |
| [ ] 1.4.7.5 Emergency reserve | 150 MJ (oversized — medical systems must not lose power) | |
| [ ] 1.4.7.6 Power personality | Moderate reactor, oversized battery and emergency reserve. Medical systems have guaranteed power priority — even during brownout, medical systems receive full power before anything else. Engineering can't deprioritise medical. No weapons to draw power. The ship runs comfortably in exploration mode but has little combat power budget. | |
| [ ] 1.4.7.7 Medical power guarantee | Medical systems exempt from brownout reduction | |

### 1.5 Weapon Loadouts Per Ship Class

Each ship class has a distinctive weapons philosophy that changes how Weapons gameplay feels.

#### 1.5.1 Scout Weapons

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.5.1.1 Beam type | Single forward-fixed light beam | |
| [ ] 1.5.1.2 Beam damage | 3.0 per hit (low) | |
| [ ] 1.5.1.3 Beam fire rate | 0.3s between shots (rapid) | |
| [ ] 1.5.1.4 Beam arc | Forward 30° only (must point ship at target) | |
| [ ] 1.5.1.5 Beam count | 1 | |
| [ ] 1.5.1.6 Torpedo tubes | 0 (no torpedoes) | |
| [ ] 1.5.1.7 Point defence | 1 light PD turret | |
| [ ] 1.5.1.8 Weapons gameplay | Strafing runs — fly at enemy, fire rapidly, loop around. Weapons is simple (aim and fire) but Helm coordination is everything because the beam only fires forward. Weapons effectiveness depends entirely on Helm keeping the nose on target. | |

#### 1.5.2 Corvette Weapons

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.5.2.1 Beam type | Standard beam array | |
| [ ] 1.5.2.2 Beam damage | 5.0 per hit | |
| [ ] 1.5.2.3 Beam fire rate | 0.8s between shots | |
| [ ] 1.5.2.4 Beam arc | 180° forward hemisphere | |
| [ ] 1.5.2.5 Beam count | 1 | |
| [ ] 1.5.2.6 Torpedo tubes | 1 | |
| [ ] 1.5.2.7 Torpedo magazine | 8 total | |
| [ ] 1.5.2.8 Point defence | 1 standard PD turret | |
| [ ] 1.5.2.9 Weapons gameplay | Light armament. The corvette avoids direct combat — its strength is EW and intelligence. Weapons is a secondary station. One beam, one torpedo tube, enough to defend but not to dominate. | |

#### 1.5.3 Frigate Weapons

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.5.3.1 Beam type | Standard beam arrays (port and starboard) | |
| [ ] 1.5.3.2 Beam damage | 6.0 per hit | |
| [ ] 1.5.3.3 Beam fire rate | 1.0s between shots | |
| [ ] 1.5.3.4 Beam arc | 180° per array (port covers left, starboard covers right, overlap at fore and aft) | |
| [ ] 1.5.3.5 Beam count | 2 (but only 1 can fire at a given target depending on facing) | |
| [ ] 1.5.3.6 Torpedo tubes | 2 | |
| [ ] 1.5.3.7 Torpedo magazine | 16 total | |
| [ ] 1.5.3.8 Point defence | 2 standard PD turrets | |
| [ ] 1.5.3.9 Weapons gameplay | The balanced loadout. Two beam arrays give good coverage — Helm doesn't need to point directly at the target, just keep them on one side. Two torpedo tubes allow salvo fire. Weapons is steadily busy but not overwhelmed. | |

#### 1.5.4 Cruiser Weapons

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.5.4.1 Beam type | Dual beam arrays (can engage 2 targets simultaneously) | |
| [ ] 1.5.4.2 Beam damage | 7.0 per hit per array | |
| [ ] 1.5.4.3 Beam fire rate | 1.2s between shots per array | |
| [ ] 1.5.4.4 Beam arc | 270° per array (nearly full coverage) | |
| [ ] 1.5.4.5 Beam count | 2 (independent targeting) | |
| [ ] 1.5.4.6 Torpedo tubes | 3 | |
| [ ] 1.5.4.7 Torpedo magazine | 24 total | |
| [ ] 1.5.4.8 Point defence | 3 standard PD turrets | |
| [ ] 1.5.4.9 Weapons gameplay | Weapons is genuinely busy. Two independently targeted beam arrays means maintaining two separate target locks. Three torpedo tubes allow rapid salvo fire or staggered launches. Weapons must prioritise which threats to engage with beams and which with torpedoes. Multi-target management is the skill. | |
| [ ] 1.5.4.10 Dual targeting UI | Weapons UI shows two target selection panels (Primary Target and Secondary Target). Each beam array is assigned to a target. Weapons can assign both to the same target for focused fire or split them. | |

#### 1.5.5 Battleship Weapons

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.5.5.1 Beam type | Heavy beam arrays | |
| [ ] 1.5.5.2 Beam damage | 10.0 per hit (devastating) | |
| [ ] 1.5.5.3 Beam fire rate | 2.0s between shots (slow but powerful) | |
| [ ] 1.5.5.4 Beam arc | 270° per array | |
| [ ] 1.5.5.5 Beam count | 2 (independent targeting) | |
| [ ] 1.5.5.6 Torpedo tubes | 4 | |
| [ ] 1.5.5.7 Torpedo magazine | 32 total | |
| [ ] 1.5.5.8 Point defence | 4 PD turrets (overlapping coverage) | |
| [ ] 1.5.5.9 Spinal mount | YES — see section 2.5.1 for full spec | |
| [ ] 1.5.5.10 Weapons gameplay | Weapons is the star station alongside Engineering. Heavy beams hit hard but slow — every shot must count. Torpedo management across 4 tubes is complex. The spinal mount is the event weapon — when it fires, the whole crew participates. Between spinal mount charges, Weapons manages beams and torpedoes against multiple threats. | |

#### 1.5.6 Carrier Weapons

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.5.6.1 Beam type | Light beam array (defensive only) | |
| [ ] 1.5.6.2 Beam damage | 4.0 per hit | |
| [ ] 1.5.6.3 Beam fire rate | 1.5s between shots | |
| [ ] 1.5.6.4 Beam arc | 180° forward | |
| [ ] 1.5.6.5 Beam count | 1 | |
| [ ] 1.5.6.6 Torpedo tubes | 0 (no torpedoes — combat power comes from drones) | |
| [ ] 1.5.6.7 Point defence | 6 PD turrets (heavy point defence to protect the flight deck from torpedoes) | |
| [ ] 1.5.6.8 Weapons gameplay | Weapons is a quiet station on a carrier. One light beam for self-defence. No torpedoes. Six PD turrets keep incoming torpedoes away from the flight deck. The carrier's offensive power is entirely in its drones — Flight Ops is the combat station. Weapons mostly monitors PD and supports with the occasional beam shot. | |

#### 1.5.7 Medical Ship Weapons

| Stat | Value | Audit |
|------|-------|-------|
| [ ] 1.5.7.1 Beam type | None (no offensive weapons) | |
| [ ] 1.5.7.2 Torpedo tubes | 0 | |
| [ ] 1.5.7.3 Point defence | 3 PD turrets (defensive only) | |
| [ ] 1.5.7.4 Weapons gameplay | The Weapons station on a medical ship has NO offensive capability. PD only. Survival depends on shields, evasion, Comms diplomacy, and escort from other ships or drone support. The medical ship is the ultimate support vessel. In a classroom with multiple crews, the medical ship crew focuses on rescue and healing while another crew's combat ship protects them. Weapons station on a medical ship is essentially PD management — the player should probably be on another station. | |

### 1.6 Shield Configuration Per Ship Class

[ ] 1.6.1 Scout shields: Low capacity (40), fast recharge (8/s). Shields flicker and drop fast but recover quickly between engagements. Defence is speed, not shields.

[ ] 1.6.2 Corvette shields: Moderate capacity (60), moderate recharge (5/s). Standard shields. ECM provides additional defence by making enemies miss.

[ ] 1.6.3 Frigate shields: Standard capacity (80), standard recharge (5/s). Balanced. Four-facing distribution works well.

[ ] 1.6.4 Cruiser shields: High capacity (120), moderate recharge (6/s). Strong shields that can absorb sustained fire. Large enough to maintain shield focus with buffer.

[ ] 1.6.5 Battleship shields: Very high capacity (200), slow recharge (4/s). Massive shield pool but slow to recover. Once shields go down, armour is the next line. The slow recharge means shield management is critical — don't let them drop completely.

[ ] 1.6.6 Carrier shields: High capacity (150), moderate recharge (5/s). Strong shields to protect the flight deck. Shield focus matters — keep the flight-deck-facing shielded to protect launching/recovering drones.

[ ] 1.6.7 Medical ship shields: Moderate capacity (70), fast recharge (7/s). Fast-recharging shields compensate for low hull. The medical ship takes hits and recovers quickly, buying time for escape or negotiation.

### 1.7 Sensor Range Per Ship Class

[ ] 1.7.1 Scout: Base sensor range 40,000 units. High resolution. Designed for reconnaissance — sees further and in more detail than anyone else.

[ ] 1.7.2 Corvette: Base sensor range 35,000 units. High resolution plus enhanced ECM detection (can detect cloaked or stealthy contacts at 50% range).

[ ] 1.7.3 Frigate: Base sensor range 30,000 units. Standard resolution. Balanced.

[ ] 1.7.4 Cruiser: Base sensor range 35,000 units. Standard resolution. Enhanced tactical overlay (contacts show predicted movement vectors).

[ ] 1.7.5 Battleship: Base sensor range 25,000 units. Standard resolution. Powerful but short-ranged sensors — the battleship relies on escorts and drones for long-range detection.

[ ] 1.7.6 Carrier: Base sensor range 30,000 units. Standard resolution. Drone sensor relay extends effective range dramatically (each scout drone adds its sensor range from its position).

[ ] 1.7.7 Medical ship: Base sensor range 35,000 units. Enhanced life signs detection (can detect crew survivors on derelicts and disabled ships at full sensor range — other ships can only detect life signs within 50% of sensor range).

### 1.8 Engine Characteristics

[ ] 1.8.1 Scout: Short-range engines. Fast acceleration, high top speed, high fuel consumption (1.5x normal). Burns fuel fast. Short mission endurance without resupply. Perfect for quick strikes and recon, poor for extended patrols.

[ ] 1.8.2 Corvette: Efficient engines. Moderate speed, LOW fuel consumption (0.7x normal). Can operate for extended periods. Good for long patrols and intelligence gathering.

[ ] 1.8.3 Frigate: Standard engines. Balanced in all regards. 1.0x fuel consumption. The baseline.

[ ] 1.8.4 Cruiser: Long-range engines. Moderate acceleration, moderate top speed, low fuel consumption (0.8x). Built for extended deployments.

[ ] 1.8.5 Battleship: Powerful but thirsty engines. Slow acceleration, moderate top speed, HIGH fuel consumption (1.8x). The battleship drinks fuel. Engineering must manage fuel carefully on long missions. Idling consumes less but transit burns through reserves.

[ ] 1.8.6 Carrier: Efficient engines for size. Moderate speed, moderate fuel consumption (1.0x). Stable platform designed for steady flight deck operations, not sprinting.

[ ] 1.8.7 Medical ship: Efficient engines. Moderate speed, low fuel consumption (0.75x). Designed for sustained operations — the medical ship needs to stay on station for extended periods.

---

## PHASE 2: UNIQUE SHIP SYSTEMS

Each ship class has one or two systems that ONLY that class possesses. These are new gameplay mechanics exclusive to the class.

### 2.1 Scout — Stealth Systems

[ ] 2.1.1 New station sub-mode: EW station gets a "STEALTH" panel when on a scout.

[ ] 2.1.2 "Silent Running" mode: All ship emissions suppressed. Ship becomes invisible to passive sensors (enemies can't see you unless they do an active scan while you're within 30% of their sensor range).

[ ] 2.1.3 Silent Running costs:
- Shields DROP TO ZERO (can't project shields while masking emissions)
- No active sensors (Science can only use passive detection — see contacts but can't scan them)
- No active communications (Comms can listen but can't transmit)
- No beam weapons (energy discharge would reveal position)
- Engines limited to 50% power (full thrust creates detectable signature)
- ECM offline (jamming is the opposite of stealth)

[ ] 2.1.4 Silent Running benefits:
- Invisible to passive sensors
- Torpedoes can be fired (brief signature, but by the time enemy detects launch point, the scout has moved)
- Perfect for: reconnaissance, ambush setup, escape, sneaking past patrols

[ ] 2.1.5 Breaking stealth: Any of the following instantly reveals the ship:
- Firing beams
- Raising shields
- Active sensor scan
- Transmitting on comms
- Engine power above 50%
- Enemy active scan while within 30% of their sensor range
- Taking damage (hull breach creates detectable atmospheric venting)

[ ] 2.1.6 Stealth activation: EW officer toggles [SILENT RUNNING]. 5-second transition as systems power down. During transition, ship is partially visible (emissions decreasing). After 5 seconds, fully stealthed.

[ ] 2.1.7 Stealth deactivation: Systems need 3 seconds to power back up. During transition, shields are still down and weapons are offline. This is the vulnerable moment — breaking stealth to attack means 3 seconds of defencelessness.

[ ] 2.1.8 Stealth status visible on all stations: amber "SILENT RUNNING" indicator. Stations affected show their limitations (Science: "PASSIVE ONLY", Weapons: "TORPEDOES ONLY", Comms: "RECEIVE ONLY").

### 2.2 Corvette — Advanced ECM Suite

[ ] 2.2.1 EW station gets additional tools only available on a corvette:

[ ] 2.2.2 Signal Spoofing: Create false sensor contacts on enemy sensors. EW can place up to 3 "ghost" contacts that appear as real ships to enemies. Ghosts have configurable signature (can mimic any ship class). Enemies may target or investigate ghosts, wasting time and ammunition.

[ ] 2.2.3 Comm Interception: Passively intercept enemy communications within sensor range. Intercepted comms are forwarded to Comms station as encrypted signals for decoding. Only the corvette can do this passively — other ships need the Comms station to actively probe.

[ ] 2.2.4 Sensor Ghosting: Make the corvette appear as a different ship class on enemy sensors. The corvette can appear as a freighter, a battleship, or any other class. Useful for bluffing ("That's not a corvette, that's a battleship — don't engage") or deception ("We're just a civilian transport").

[ ] 2.2.5 Targeted Frequency Lock: When EW identifies an enemy's communication frequency (from Comms intercept or Science scan), EW can lock that frequency and completely block that enemy's communications. The enemy can't call for reinforcements, can't coordinate with allies, can't receive orders. Only the corvette can do a full frequency lock — other ships can jam but not selectively lock.

### 2.3 Frigate — Modular Equipment Bays

[ ] 2.3.1 The frigate has 2 modular equipment bays that are configured in the lobby before launch.

[ ] 2.3.2 Equipment modules available (choose 2 from this list):

[ ] 2.3.2.1 Extra Torpedo Magazine: +8 torpedo capacity, adds 1 torpedo tube. Weapons gets more ammunition and a third tube.

[ ] 2.3.2.2 Enhanced Sensor Array: +30% sensor range, +20% scan speed. Science gets better tools.

[ ] 2.3.2.3 Marine Barracks: +1 marine squad (4 marines). Security gets an extra team for boarding defence or escort.

[ ] 2.3.2.4 Drone Hangar Expansion: +2 hangar slots, +1 combat drone. Flight Ops gets more air power.

[ ] 2.3.2.5 Medical Ward Upgrade: +2 medical beds, +1 quarantine slot, +20% medical supplies. Medical gets enhanced capability.

[ ] 2.3.2.6 Cargo Hold: Can carry supplies for trade, mission objectives, salvage. Enables trade missions and salvage operations. Also carries +50% fuel reserves.

[ ] 2.3.2.7 Armour Plating: +15 armour, +20 hull. Ship is tougher but max speed reduced by 10% (extra weight).

[ ] 2.3.2.8 Cloaking Device: Ship gains scout-style silent running (see 2.1) but with higher power drain and shorter duration (60 seconds max before systems overheat). Powerful but temporary stealth.

[ ] 2.3.2.9 Mining Equipment: Can harvest resources from asteroids. Creates a new mini-game for Engineering: target asteroid, deploy mining beam, collect resources (fuel, rare materials for trade). Enables resource-gathering missions.

[ ] 2.3.3 Modules are visually represented in the lobby as slots with drag-and-drop selection.

[ ] 2.3.4 Module effects are applied during game initialisation and persist for the entire mission.

[ ] 2.3.5 Module choice is shown in mission debrief.

### 2.4 Cruiser — Flag Bridge

[ ] 2.4.1 Captain's station gets enhanced tactical capabilities only on a cruiser.

[ ] 2.4.2 Tactical Planning Overlay: Captain can draw on the tactical map — waypoints, movement arrows, danger zones, objective markers. These drawings are visible to Helm and Tactical as "Captain's Plan." This is a visual communication tool: the Captain draws the battle plan and the crew executes it.

[ ] 2.4.3 Engagement Timeline: A timeline display showing predicted events — estimated time to torpedo range, estimated time to beam range, enemy estimated arrival, mission deadline. Tactical station manages this on other ships; on a cruiser the Captain gets it directly.

[ ] 2.4.4 Target Priority Queue: Captain can set a priority list of targets. Weapons sees this as "Captain's Priority: 1. Cruiser, 2. Escort, 3. Escort." Weapons can override but it creates a command framework.

[ ] 2.4.5 Fleet Coordination (future-proofing): Placeholder for multi-ship coordination when internet play is added. The cruiser Captain would see allied ship positions and be able to issue fleet-level orders.

### 2.5 Battleship — Spinal Mount Weapon & Layered Armour

#### 2.5.1 Spinal Mount

[ ] 2.5.1.1 A massive forward-facing weapon that runs the length of the ship. Devastating damage in a narrow forward arc.

[ ] 2.5.1.2 Stats:
- Damage: 150.0 (one-shot kill on most ships, heavy damage to stations and large targets)
- Arc: 5° forward only (ship must be precisely aligned)
- Charge time: 30 seconds
- Power draw: 600 MJ/s during charge (40% of reactor)
- Cooldown: 120 seconds after firing before recharge can begin
- Accuracy: 95% against stationary targets, 70% against moving targets, 40% against fast-moving small targets

[ ] 2.5.1.3 Firing sequence (whole-crew event):
1. Weapons initiates spinal mount charge: [CHARGE SPINAL MOUNT]
2. Captain must AUTHORISE: Captain gets "SPINAL MOUNT CHARGE REQUESTED — AUTHORISE?" prompt. Without Captain authorisation, charge does not begin. This is a command weapon.
3. Engineering sees 40% power drain begin. Must manage brownout on other systems during charge. Typically reduces shields or engines.
4. Helm must align ship within 5° of target. A "SPINAL ALIGNMENT" indicator shows on Helm: green when aligned, amber when close, red when off-target. Helm must hold steady for the full 30-second charge.
5. Science provides targeting data — range, velocity, predicted position at time of fire. If Science is offline, accuracy drops by 20%.
6. 30-second countdown visible on ALL stations. Tension builds.
7. At zero: Weapons presses [FIRE]. If alignment is good (within 5°), the weapon fires. If alignment has drifted, weapon fires but with reduced accuracy.
8. VISUAL: massive beam/projectile on the viewscreen. Screen shake. Audio: deep charging hum building to a thunderous discharge.
9. Power drain ends. 120-second cooldown begins.

[ ] 2.5.1.4 If the ship takes damage during charge that disrupts Helm alignment (hit causes ship to rotate), the charge is NOT interrupted but accuracy drops. The crew must decide: fire inaccurately or restart the charge.

[ ] 2.5.1.5 If the ship takes critical reactor damage during charge, the charge IS interrupted. Power is lost, charge resets to 0.

[ ] 2.5.1.6 Spinal mount appears as a new panel on the Weapons station for battleships only. Other ship classes do not see this panel.

#### 2.5.2 Layered Armour

[ ] 2.5.2.1 Battleship armour (40) functions as described in section 1.3, with an additional mechanic: armour zones. The battleship has 4 armour zones matching shield facings (fore, aft, port, starboard). Each zone has independent armour value (10 per zone, 40 total).

[ ] 2.5.2.2 When a hit comes from a specific direction, it depletes the armour zone for that facing. A torpedo from ahead depletes fore armour. When fore armour is 0, hits from ahead bypass armour entirely and go straight to hull — even if port armour is still at 10.

[ ] 2.5.2.3 This creates positioning gameplay for Helm: keep the strong armour facing toward the enemy. If fore armour is depleted but starboard is full, turn the ship to present the starboard side.

[ ] 2.5.2.4 Engineering can see armour per facing on their ship diagram (same layout as shield focus).

[ ] 2.5.2.5 Repair teams can repair armour zones, but only to 75% of original value (7.5 per zone maximum from field repair). Full restoration requires docking.

### 2.6 Carrier — Flight Control Centre

[ ] 2.6.1 Enhanced Flight Ops with squadron management. Flight Ops UI has a "SQUADRON" panel that allows grouping drones into squadrons and issuing orders to the group.

[ ] 2.6.2 CAP (Combat Air Patrol): Automated drone patrol that maintains coverage without Flight Ops micromanaging. Set a CAP zone (region on the map), assign 2-4 drones, and they automatically patrol the zone, engage hostiles, and return for refuelling in rotation. Flight Ops monitors but doesn't have to set individual waypoints.

[ ] 2.6.3 Scramble: One-button launch of all ready drones in the hangar simultaneously. Normal ships launch one drone at a time per tube. The carrier has 3 launch tubes and can launch 3 simultaneously. "SCRAMBLE" launches all ready drones from all tubes in rapid sequence (3-second intervals instead of 8-second normal launch time per drone).

[ ] 2.6.4 Drone Recovery Priority: Carrier's enhanced recovery system has 2 recovery slots (other ships have 1). Can recover 2 drones simultaneously.

[ ] 2.6.5 Hangar Repair: Carrier's maintenance facility repairs drones 50% faster than other ships. Turnaround time is reduced by half.

### 2.7 Medical Ship — Hospital Systems

[ ] 2.7.1 Treatment beds: 8 (vs 2-4 on other ships). Can treat many patients simultaneously.

[ ] 2.7.2 Surgical Theatre: Can perform complex procedures that other ships cannot. Specifically: reattaching severed limbs, treating acute radiation syndrome fully (other ships can only stabilise), neurosurgery for critical head injuries. These procedures take longer (60-90 seconds) but achieve full recovery instead of partial.

[ ] 2.7.3 Quarantine Wing: 4 isolation slots (vs 2 on other ships). Can handle a serious contagion outbreak without running out of quarantine space.

[ ] 2.7.4 Triage AI: When Medical station is uncrewed, the medical ship's AI automatically admits and treats patients in priority order. Other ships' medical bays do nothing when uncrewed. This makes the medical ship resilient — medical functions continue even if the Medical player is handling another station.

[ ] 2.7.5 Search and Rescue Beacon: Ship broadcasts a rescue beacon on all frequencies. This has two effects:
- Friendly and civilian ships within sensor range are more likely to come to the medical ship for help (generates more rescue/diplomatic missions via Comms)
- Enemies may hesitate to attack (small chance of enemies breaking off attack against a medical ship — depends on faction and difficulty)

[ ] 2.7.6 Medical Resupply: Medical ship carries 200% normal medical supplies. Can also transfer supplies to allied ships if docked alongside.

---

## PHASE 3: PRE-MISSION LOADOUT CONFIGURATION

### 3.1 Lobby Configuration Screen

[ ] 3.1.1 After ship class selection in the lobby, a new "CONFIGURE SHIP" panel appears before the game starts.

[ ] 3.1.2 The configuration screen shows the ship with its base stats and allows modification within defined limits.

[ ] 3.1.3 Only the player who created the game (host) can modify the loadout. Other players can view but not change.

[ ] 3.1.4 A [DEFAULT LOADOUT] button resets everything to standard configuration for that ship class.

[ ] 3.1.5 Configuration is saved with the game state (resume preserves loadout).

[ ] 3.1.6 Configuration is shown in the mission debrief.

### 3.2 Torpedo Loadout

[ ] 3.2.1 The torpedo magazine has a total capacity defined by ship class. The player distributes this capacity among available torpedo types.

[ ] 3.2.2 Available torpedo types and costs (each torpedo costs capacity points):
- Standard (1 point each): reliable, moderate damage, unguided
- Homing (2 points each): tracks target, moderate damage
- Ion (2 points each): disables systems instead of damaging hull
- Piercing (2 points each): penetrates shields, reduced hull damage
- Heavy (3 points each): high damage, slow, large blast radius
- Proximity (2 points each): detonates near target, good vs fast ships
- Nuclear (5 points each): devastating damage, huge blast radius, damages everything nearby including friendlies
- Experimental (4 points each): random special effect per torpedo

[ ] 3.2.3 UI shows torpedo type grid with +/- buttons and remaining capacity counter.

[ ] 3.2.4 Preset loadout buttons: [BALANCED], [AGGRESSIVE], [DEFENSIVE], [STEALTH].

[ ] 3.2.5 Default loadout per ship class uses the balanced preset.

### 3.3 Power Profile

[ ] 3.3.1 Choose reactor tuning that affects the power budget for the entire mission:

[ ] 3.3.2 "Balanced" (default): No modifications. Standard power distribution.

[ ] 3.3.3 "Combat": Weapons and shields power systems receive +15% efficiency (consume 15% less power for the same output). Sensors and engines receive -15% efficiency (consume 15% more). Biased toward fighting.

[ ] 3.3.4 "Exploration": Sensors and engines receive +15% efficiency. Weapons and shields receive -15% efficiency. Biased toward scanning and travel.

[ ] 3.3.5 "Emergency": Emergency reserve is 50% larger. Sustained reactor output reduced by 10%. More buffer for crises, less peak performance.

[ ] 3.3.6 "Overclocked": Reactor output +10%. Battery capacity -25%. Coolant system starts at 80% health instead of 100% (overclocking strains the reactor). High risk, high reward — more power but less margin for error and higher risk of overheat.

[ ] 3.3.7 Power profile shown on Engineering station as "REACTOR TUNING: [profile name]".

### 3.4 Crew Complement Bias

[ ] 3.4.1 Total crew count is fixed by ship class. But the distribution between departments can be adjusted.

[ ] 3.4.2 Adjustable departments: Engineering, Security, Medical, Science, Weapons, Flight Ops.

[ ] 3.4.3 Each department has a default crew count and can be adjusted ±2 from default.

[ ] 3.4.4 Increasing one department by 1 requires decreasing another by 1 (zero-sum).

[ ] 3.4.5 UI shows each department with crew count and +/- buttons. Running total shown.

[ ] 3.4.6 Effect: crew_factor_for_system is based on actual crew assigned. More engineering crew = better crew factor for engineering systems = faster repairs and better reactor management.

[ ] 3.4.7 Preset buttons: [BALANCED], [COMBAT] (extra weapons/security, fewer science/medical), [SCIENCE] (extra science/medical, fewer weapons/security), [REPAIR] (extra engineering, fewer everything else).

### 3.5 Drone Loadout

[ ] 3.5.1 Ships with hangars can choose which drone types to bring within hangar capacity.

[ ] 3.5.2 Each drone type costs 1 hangar slot.

[ ] 3.5.3 UI shows hangar slot grid with drone type dropdown per slot.

[ ] 3.5.4 Ship class defines available drone types (not all ships can carry all types — see v0.06.5 complement table).

[ ] 3.5.5 Preset buttons: [BALANCED], [RECON] (more scouts), [ASSAULT] (more combat), [SUPPORT] (more rescue/survey).

### 3.6 Equipment Modules (Frigate Only)

[ ] 3.6.1 Frigate shows 2 module slots in the configuration screen.

[ ] 3.6.2 Each slot has a dropdown showing available modules (see section 2.3.2).

[ ] 3.6.3 Cannot select the same module twice.

[ ] 3.6.4 Module effects described clearly in tooltip on hover.

[ ] 3.6.5 Visual: ship schematic shows module positions on the hull.

---

## PHASE 4: VISUAL IDENTITY

### 4.1 Ship Silhouettes

Each ship class must have a distinct silhouette that is recognisable at a glance on the viewscreen, on maps, and in the UI.

[ ] 4.1.1 Scout: Small, sleek, angular. Narrow profile. Think fighter jet or racing yacht. Immediately reads as "fast."

[ ] 4.1.2 Corvette: Compact, bristling with antenna arrays (ECM equipment). Slightly wider than a scout. Distinctive sensor dome or antenna cluster.

[ ] 4.1.3 Frigate: Clean, symmetrical, medium-sized. The "standard" military ship shape. Recognisable as the baseline.

[ ] 4.1.4 Cruiser: Large, commanding, prominent bridge section. Wider than a frigate, with visible weapon emplacements. Looks like it's in charge.

[ ] 4.1.5 Battleship: Massive, heavy, angular armour plates visible. Spinal mount visible as a long central structure. Radiates power and weight. Looks like it could absorb anything.

[ ] 4.1.6 Carrier: Wide, flat flight deck visible along one side. Asymmetric profile. Clearly a floating airfield. Hangar bay openings visible.

[ ] 4.1.7 Medical ship: White/light-coloured accents (unlike the military grey/green of other ships). Prominent red cross or medical symbol. Non-threatening profile. Rounded edges rather than angular.

[ ] 4.1.8 Each silhouette used as the ship wireframe on the Captain's viewscreen.

[ ] 4.1.9 Each silhouette used as the ship icon on Engineering's shield focus panel (the 2D top-down view where you drag the shield focus point).

[ ] 4.1.10 Each silhouette used as the ship icon on map views across all stations.

[ ] 4.1.11 Enemy ships encountered should also use class-appropriate silhouettes (enemy scout looks different from enemy battleship on the viewscreen wireframe).

### 4.2 Interior Layouts

Each ship class has a different interior map layout that affects Security and boarding gameplay.

[ ] 4.2.1 Scout: 3 decks, 3-4 rooms per deck. Compact. Boarders reach the bridge in 10-15 seconds. Boarding is fast and lethal — Security must respond instantly. One locked door makes a huge difference.

[ ] 4.2.2 Corvette: 4 decks, 4-5 rooms per deck. Slightly more room to manoeuvre. Secret access tunnels (ECM/intelligence theme) that Security knows about but boarders don't — marines can use shortcuts.

[ ] 4.2.3 Frigate: 5 decks, 5-6 rooms per deck. Standard layout. Multiple paths between decks giving Security tactical options for ambush and containment.

[ ] 4.2.4 Cruiser: 6 decks, 6-7 rooms per deck. Large interior. Bridge is well-protected (2 locked doors and a security checkpoint by default). Boarders have a long path to the bridge. Security has time to respond but also more area to cover.

[ ] 4.2.5 Battleship: 8 decks, 6-8 rooms per deck. Enormous interior. Boarding is a sustained battle through many compartments. Security has depth of defence — multiple fallback positions. But if boarders establish a foothold, dislodging them is hard.

[ ] 4.2.6 Carrier: 7 decks including 2 hangar decks. Hangar decks are LARGE open spaces — easy for boarders to move through but also easy for marines to see. The flight deck is vulnerable to boarding because it has external openings.

[ ] 4.2.7 Medical ship: 5 decks including 2 medical decks. Medical decks have biohazard containment features that Security can activate to slow boarders (emergency quarantine locks).

[ ] 4.2.8 Each layout defined as a JSON data structure with rooms, connections, and default door states.

[ ] 4.2.9 Interior layouts used by Security, DC, Engineering (repair team routing), and the Janitor.

### 4.3 Station Display Adaptation

Certain stations should look different depending on ship class:

[ ] 4.3.1 Engineering shield focus panel uses the correct ship silhouette for the selected class.

[ ] 4.3.2 Captain's viewscreen shows the correct ship wireframe.

[ ] 4.3.3 Weapons shows spinal mount panel ONLY on battleship.

[ ] 4.3.4 Weapons shows dual targeting panel ONLY on cruiser and battleship.

[ ] 4.3.5 Flight Ops shows squadron management ONLY on carrier.

[ ] 4.3.6 EW shows stealth panel ONLY on scout.

[ ] 4.3.7 EW shows advanced ECM tools ONLY on corvette.

[ ] 4.3.8 Medical shows surgical theatre ONLY on medical ship.

[ ] 4.3.9 Engineering shows modular bay status ONLY on frigate (and only the equipped modules).

[ ] 4.3.10 Lobby ship selection shows correct silhouette preview with stat summary for each class.

---

## PHASE 5: INTEGRATION AND BALANCE

### 5.1 Ship Class JSON Schema

[ ] 5.1.1 All ship class data defined in JSON files (one per class) in a ships/ directory.

[ ] 5.1.2 JSON schema includes ALL stats from Phase 1, unique system flags from Phase 2, default loadout from Phase 3, and interior layout from Phase 4.

[ ] 5.1.3 Schema is validated at game start — missing or invalid values cause clear error messages.

[ ] 5.1.4 Example schema structure:

```json
{
    "class_id": "frigate",
    "display_name": "Frigate",
    "description": "Balanced multi-role vessel...",
    "physical": {
        "hull": 120,
        "max_speed": 160,
        "acceleration": 30,
        "turn_rate": 90,
        "target_profile": 0.75,
        "armour": 10,
        "handling_trait": "clean"
    },
    "crew": {
        "complement_min": 18,
        "complement_max": 24,
        "decks": 5,
        "default_distribution": { ... }
    },
    "power_grid": { ... },
    "weapons": { ... },
    "shields": { ... },
    "sensors": { ... },
    "engines": { ... },
    "drones": { ... },
    "unique_systems": [ ... ],
    "modular_bays": 2,
    "interior_layout": { ... },
    "silhouette": "frigate.svg"
}
```

[ ] 5.1.5 A JSON validation script exists that checks all ship class files against the schema.

### 5.2 Balance Testing

[ ] 5.2.1 Create tests/test_ship_balance.py that verifies balance properties:

[ ] 5.2.2 No ship class has best-in-class for ALL stats (every ship must have a weakness).

[ ] 5.2.3 Verify the stat spread: the ratio between best and worst for each stat should be at least 2x (e.g., battleship hull 300 vs scout hull 60 = 5x spread — good).

[ ] 5.2.4 Verify power budget: at default allocations, no ship class is in brownout (power surplus or balanced at default).

[ ] 5.2.5 Verify DPS (damage per second): calculate theoretical beam DPS per class. Scout: 10.0 DPS (3.0 × 1/0.3). Battleship: 10.0 DPS (10.0 × 1/2.0). These should be similar for beams (different delivery: many light hits vs few heavy hits) with torpedo and spinal mount creating the class differences in burst damage.

[ ] 5.2.6 Verify TTK (time to kill): calculate theoretical time for each class to destroy each other class. Create a balance matrix. No matchup should be instant (<5 seconds) except spinal mount vs scout. Most 1v1 matchups should be 30-120 seconds.

[ ] 5.2.7 Verify survivability: hull × (1 + armour_factor) × shield_capacity × target_profile_inverse gives an effective HP value. Spread between classes should be 4-6x (scout to battleship).

### 5.3 Regression Testing

[ ] 5.3.1 All existing tests pass with the new ship class system (tests should work with any ship class, not assume frigate).

[ ] 5.3.2 Tests are parameterised across ship classes where appropriate (e.g., test power grid for all 7 classes).

[ ] 5.3.3 Save/resume serialisation includes all new stats, loadout, and unique system states.

[ ] 5.3.4 Lobby correctly shows ship selection, configuration, and transmits to server.

[ ] 5.3.5 All stations correctly adapt their displays based on ship class.

### 5.4 Test Targets

| Test File | Target | Audit |
|-----------|--------|-------|
| [ ] 5.4.1 tests/test_ship_classes.py | 50+ tests (stats, each class) | |
| [ ] 5.4.2 tests/test_target_profile.py | 15+ tests (hit probability) | |
| [ ] 5.4.3 tests/test_armour.py | 20+ tests (damage reduction, degradation, zones) | |
| [ ] 5.4.4 tests/test_ship_balance.py | 15+ tests (balance matrix, stat spreads) | |
| [ ] 5.4.5 tests/test_spinal_mount.py | 25+ tests (charge, fire, alignment, power) | |
| [ ] 5.4.6 tests/test_stealth.py | 20+ tests (silent running, detection, break) | |
| [ ] 5.4.7 tests/test_advanced_ecm.py | 20+ tests (spoofing, interception, ghosting, freq lock) | |
| [ ] 5.4.8 tests/test_modular_bays.py | 15+ tests (module effects, lobby selection) | |
| [ ] 5.4.9 tests/test_loadout.py | 20+ tests (torpedo, power profile, crew, drone) | |
| [ ] 5.4.10 tests/test_ship_interiors.py | 15+ tests (layout per class, room counts, paths) | |
| Total | 215+ new tests | |

---

## BUILD ORDER

| Phase | Part | Description | Risk | Depends On |
|-------|------|-------------|------|------------|
| 1 | 1.1-1.2 | Physical profiles + target profile | Low | Ship JSON |
| 1 | 1.3 | Armour system | Medium | Damage pipeline |
| 1 | 1.4 | Power grids per class | Low | Existing power grid |
| 1 | 1.5 | Weapon loadouts per class | Medium | Weapons station |
| 1 | 1.6 | Shield configs | Low | Shield system |
| 1 | 1.7 | Sensor ranges | Low | Science station |
| 1 | 1.8 | Engine characteristics | Low | Helm/physics |
| 2 | 2.1 | Scout stealth | High | EW station |
| 2 | 2.2 | Corvette ECM | High | EW station, Comms |
| 2 | 2.3 | Frigate modules | Medium | Lobby UI |
| 2 | 2.4 | Cruiser flag bridge | Medium | Captain station |
| 2 | 2.5 | Battleship spinal + armour zones | High | Weapons, Helm, Eng |
| 2 | 2.6 | Carrier flight centre | Medium | Flight Ops |
| 2 | 2.7 | Medical hospital | Medium | Medical station |
| 3 | 3.1-3.6 | Lobby configuration | Medium | Ship JSON, lobby |
| 4 | 4.1-4.3 | Visual identity | Low | SVG creation |
| 5 | 5.1-5.4 | Integration and balance | Medium | Everything |

**Commit after each part.** Format: "v0.07-X.Y: description"

**Pytest after each part.** Zero regressions.

---

## STOP CONDITIONS

- Ship class stats produce unplayable balance (one class dominates all others)
- Unique systems create server performance issues (stealth detection checks, spinal mount power calculations)
- Interior layout generation has pathfinding bugs
- Lobby configuration screen is too complex for students to use quickly (target: <60 seconds to configure)
- Any station crashes when loading on a ship class that doesn't have its expected systems (e.g., Weapons on medical ship with no beams)
- Save/resume doesn't preserve loadout and class-specific state

---

## CLASSROOM GUIDE (for documentation)

| Class Size | Recommended Ship | Reasoning |
|-----------|-----------------|-----------|
| 2-4 students | Scout | Few stations, tight crew, every person matters |
| 4-6 students | Corvette | More stations, intelligence focus |
| 6-8 students | Frigate | Balanced, every station has a role |
| 8-10 students | Cruiser | Full station complement, command structure |
| 10-14 students | Battleship or Carrier | Every station busy, complex operations |
| 2 groups | Combat ship + Medical ship | Cooperative multi-crew mission |

---

*End of v0.07 Specification*
*Total audit checkboxes: 243*
*Total test target: 215+ new tests*
