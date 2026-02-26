# STARBRIDGE v0.07 — PHASE 6: QUARTERMASTER STATION
## Complete Specification & Audit Checklist

**Version:** 1.0
**Date:** February 2026
**Author:** Peter Howse / Claude
**Status:** Specification
**Depends on:** v0.07 Phases 1–5 (ship class differentiation must be in place)

---

## OVERVIEW

The Quartermaster is a new station responsible for resource management, procurement, and trade negotiation. Every other station consumes resources. The Quartermaster is the only station that acquires them.

The station has two modes: outward-facing (negotiating with external vendors) and inward-facing (managing the ship's consumable inventory, burn rates, and allocation). This dual role means the Quartermaster is never idle — when there's nobody to trade with, they're forecasting depletion and planning resupply.

**Design Principle:** The Quartermaster creates crew communication. Every station talks to the Quartermaster about resources. The Quartermaster talks to the Captain about route planning. The role is a communication hub that drives the cross-station conversation Starbridge is built around.

---

## 6.1 CONSUMABLE RESOURCE SYSTEM

Before the Quartermaster can manage resources, the game needs a comprehensive consumable system where supplies are finite and deplete through gameplay.

### 6.1.1 Resource Types

[ ] 6.1.1.1 **Fuel**: Powers the reactor and engines. Depleted by engine thrust, reactor idle consumption, and system power draw. When fuel reaches 0, reactor shuts down — all powered systems fail. This is the mission-ending resource. Measured in fuel units (FU).

[ ] 6.1.1.2 **Torpedoes**: Individual items by type (standard, homing, ion, piercing, heavy, proximity, nuclear, experimental). Each torpedo is a discrete item. When the magazine is empty, Weapons cannot fire torpedoes. Loaded from lobby loadout, replenished by trade.

[ ] 6.1.1.3 **Medical supplies**: Consumed by Medical when treating patients. Each treatment consumes a quantity proportional to injury severity (minor: 1 unit, moderate: 3, severe: 5, critical: 8). When medical supplies reach 0, Medical can only perform basic triage (stabilise but not heal). Measured in medical supply units (MSU).

[ ] 6.1.1.4 **Repair materials**: Consumed by Engineering when performing major repairs (component replacement, hull breach patching, armour restoration). Minor repairs (recalibration, rerouting) do not consume materials. Each major repair consumes 2–10 units depending on severity. When repair materials reach 0, Engineering can only perform minor repairs. Measured in repair material units (RMU).

[ ] 6.1.1.5 **Drone fuel**: Separate from ship fuel. Consumed when drones are active (rates defined per drone type in v0.06.5). When drone fuel reaches 0, no drones can launch. Recovered drones cannot refuel. Measured in drone fuel units (DFU).

[ ] 6.1.1.6 **Drone parts**: Consumed when repairing damaged drones during turnaround. Hull damage repair costs 1 part per 10% hull restored. When drone parts reach 0, damaged drones cannot be repaired (can still launch damaged). Replacement drones cost 5 parts each (cannot replace destroyed drones without parts). Measured in drone part units (DPU).

[ ] 6.1.1.7 **Ammunition**: Marine small arms ammunition for Security. Each combat round in which marines engage consumes 5 ammo per active marine squad. When ammo reaches 0, marine firepower drops by 60% (melee only). Measured in ammunition units (AMU).

[ ] 6.1.1.8 **Provisions**: Food, water, life support consumables. Depleted at a constant rate per crew member per minute. When provisions reach 0, crew morale drops 2% per minute and crew effectiveness drops 1% per minute (hunger, dehydration). Not immediately fatal but degrades everything over time. Measured in provision units (PVU).

### 6.1.2 Starting Quantities Per Ship Class

Each ship class has different starting quantities reflecting its size, role, and storage capacity.

#### Scout

| Resource | Starting | Capacity | Burn Rate | Audit |
|----------|----------|----------|-----------|-------|
| [ ] 6.1.2.1 Fuel | 600 FU | 600 FU | Engine: 1.5 FU/s at full, Reactor idle: 0.3 FU/s | |
| [ ] 6.1.2.2 Torpedoes | 0 (no tubes) | 0 | N/A | |
| [ ] 6.1.2.3 Medical supplies | 30 MSU | 40 MSU | Per treatment | |
| [ ] 6.1.2.4 Repair materials | 20 RMU | 30 RMU | Per major repair | |
| [ ] 6.1.2.5 Drone fuel | 100 DFU | 100 DFU | Per drone type spec | |
| [ ] 6.1.2.6 Drone parts | 5 DPU | 10 DPU | Per drone repair | |
| [ ] 6.1.2.7 Ammunition | 30 AMU | 40 AMU | 5 per squad per round | |
| [ ] 6.1.2.8 Provisions | 200 PVU | 200 PVU | 0.02 PVU/crew/min | |

#### Corvette

| Resource | Starting | Capacity | Burn Rate | Audit |
|----------|----------|----------|-----------|-------|
| [ ] 6.1.2.9 Fuel | 900 FU | 900 FU | Engine: 0.7 FU/s at full, Reactor idle: 0.4 FU/s | |
| [ ] 6.1.2.10 Torpedoes | Per loadout | 8 capacity points | Per fire | |
| [ ] 6.1.2.11 Medical supplies | 40 MSU | 60 MSU | Per treatment | |
| [ ] 6.1.2.12 Repair materials | 30 RMU | 40 RMU | Per major repair | |
| [ ] 6.1.2.13 Drone fuel | 150 DFU | 150 DFU | Per drone type spec | |
| [ ] 6.1.2.14 Drone parts | 8 DPU | 15 DPU | Per drone repair | |
| [ ] 6.1.2.15 Ammunition | 40 AMU | 60 AMU | 5 per squad per round | |
| [ ] 6.1.2.16 Provisions | 350 PVU | 350 PVU | 0.02 PVU/crew/min | |

#### Frigate

| Resource | Starting | Capacity | Burn Rate | Audit |
|----------|----------|----------|-----------|-------|
| [ ] 6.1.2.17 Fuel | 1200 FU | 1200 FU | Engine: 1.0 FU/s at full, Reactor idle: 0.5 FU/s | |
| [ ] 6.1.2.18 Torpedoes | Per loadout | 16 capacity points | Per fire | |
| [ ] 6.1.2.19 Medical supplies | 60 MSU | 80 MSU | Per treatment | |
| [ ] 6.1.2.20 Repair materials | 50 RMU | 60 RMU | Per major repair | |
| [ ] 6.1.2.21 Drone fuel | 200 DFU | 200 DFU | Per drone type spec | |
| [ ] 6.1.2.22 Drone parts | 12 DPU | 20 DPU | Per drone repair | |
| [ ] 6.1.2.23 Ammunition | 50 AMU | 80 AMU | 5 per squad per round | |
| [ ] 6.1.2.24 Provisions | 500 PVU | 500 PVU | 0.02 PVU/crew/min | |

#### Cruiser

| Resource | Starting | Capacity | Burn Rate | Audit |
|----------|----------|----------|-----------|-------|
| [ ] 6.1.2.25 Fuel | 1800 FU | 1800 FU | Engine: 0.8 FU/s at full, Reactor idle: 0.7 FU/s | |
| [ ] 6.1.2.26 Torpedoes | Per loadout | 24 capacity points | Per fire | |
| [ ] 6.1.2.27 Medical supplies | 80 MSU | 100 MSU | Per treatment | |
| [ ] 6.1.2.28 Repair materials | 70 RMU | 90 RMU | Per major repair | |
| [ ] 6.1.2.29 Drone fuel | 300 DFU | 300 DFU | Per drone type spec | |
| [ ] 6.1.2.30 Drone parts | 15 DPU | 25 DPU | Per drone repair | |
| [ ] 6.1.2.31 Ammunition | 70 AMU | 100 AMU | 5 per squad per round | |
| [ ] 6.1.2.32 Provisions | 800 PVU | 800 PVU | 0.02 PVU/crew/min | |

#### Battleship

| Resource | Starting | Capacity | Burn Rate | Audit |
|----------|----------|----------|-----------|-------|
| [ ] 6.1.2.33 Fuel | 2400 FU | 2400 FU | Engine: 1.8 FU/s at full, Reactor idle: 1.0 FU/s | |
| [ ] 6.1.2.34 Torpedoes | Per loadout | 32 capacity points | Per fire | |
| [ ] 6.1.2.35 Medical supplies | 100 MSU | 120 MSU | Per treatment | |
| [ ] 6.1.2.36 Repair materials | 100 RMU | 120 RMU | Per major repair | |
| [ ] 6.1.2.37 Drone fuel | 400 DFU | 400 DFU | Per drone type spec | |
| [ ] 6.1.2.38 Drone parts | 20 DPU | 30 DPU | Per drone repair | |
| [ ] 6.1.2.39 Ammunition | 100 AMU | 150 AMU | 5 per squad per round | |
| [ ] 6.1.2.40 Provisions | 1200 PVU | 1200 PVU | 0.02 PVU/crew/min | |

#### Carrier

| Resource | Starting | Capacity | Burn Rate | Audit |
|----------|----------|----------|-----------|-------|
| [ ] 6.1.2.41 Fuel | 1600 FU | 1600 FU | Engine: 1.0 FU/s at full, Reactor idle: 0.8 FU/s | |
| [ ] 6.1.2.42 Torpedoes | 0 (no tubes) | 0 | N/A | |
| [ ] 6.1.2.43 Medical supplies | 70 MSU | 90 MSU | Per treatment | |
| [ ] 6.1.2.44 Repair materials | 60 RMU | 80 RMU | Per major repair | |
| [ ] 6.1.2.45 Drone fuel | 800 DFU | 800 DFU (massive — the carrier's primary combat resource) | Per drone type spec | |
| [ ] 6.1.2.46 Drone parts | 40 DPU | 60 DPU | Per drone repair | |
| [ ] 6.1.2.47 Ammunition | 60 AMU | 80 AMU | 5 per squad per round | |
| [ ] 6.1.2.48 Provisions | 1000 PVU | 1000 PVU | 0.02 PVU/crew/min | |

#### Medical Ship

| Resource | Starting | Capacity | Burn Rate | Audit |
|----------|----------|----------|-----------|-------|
| [ ] 6.1.2.49 Fuel | 1000 FU | 1000 FU | Engine: 0.75 FU/s at full, Reactor idle: 0.4 FU/s | |
| [ ] 6.1.2.50 Torpedoes | 0 (no weapons) | 0 | N/A | |
| [ ] 6.1.2.51 Medical supplies | 200 MSU | 250 MSU (massive — the medical ship's primary resource) | Per treatment | |
| [ ] 6.1.2.52 Repair materials | 40 RMU | 50 RMU | Per major repair | |
| [ ] 6.1.2.53 Drone fuel | 200 DFU | 200 DFU | Per drone type spec | |
| [ ] 6.1.2.54 Drone parts | 10 DPU | 15 DPU | Per drone repair | |
| [ ] 6.1.2.55 Ammunition | 30 AMU | 40 AMU | 5 per squad per round | |
| [ ] 6.1.2.56 Provisions | 600 PVU | 600 PVU | 0.02 PVU/crew/min | |

### 6.1.3 Cargo Hold

[ ] 6.1.3.1 Each ship has a cargo_capacity (units of space) for carrying trade goods, salvage, and surplus supplies. Cargo capacity is separate from the resource stores above — resources are stored in dedicated systems (fuel tanks, torpedo magazines, etc.), cargo is general-purpose storage.

[ ] 6.1.3.2 Cargo capacity per ship class:
- Scout: 20 units
- Corvette: 40 units
- Frigate: 60 units (80 with Cargo Hold module from 2.3.2.6)
- Cruiser: 80 units
- Battleship: 100 units
- Carrier: 70 units
- Medical ship: 50 units

[ ] 6.1.3.3 Trade goods occupy cargo space. Each trade good has a size (1–5 units) and a base value. The Quartermaster decides what to carry.

[ ] 6.1.3.4 Surplus resources can be moved to cargo for trade. Converting 10 torpedoes from the magazine to cargo frees magazine space and creates tradeable items. This is a one-way decision within a mission — cargo torpedoes can be sold but not reloaded into the magazine without a dock.

[ ] 6.1.3.5 Salvage from disabled ships occupies cargo space. The Quartermaster must decide what salvage is worth taking given remaining cargo capacity.

### 6.1.4 Resource Depletion Consequences

[ ] 6.1.4.1 Each resource has a WARNING threshold (25% remaining) and a CRITICAL threshold (10% remaining). At warning, the Quartermaster gets an amber alert. At critical, all stations see a red warning for that resource.

[ ] 6.1.4.2 Fuel at 0: Reactor shutdown. All powered systems fail. Ship is adrift. Emergency battery provides limited power for life support and comms only. Mission effectively over unless resupply arrives.

[ ] 6.1.4.3 Torpedoes at 0: Weapons limited to beams and PD. Significant combat capability reduction for ships that rely on torpedoes.

[ ] 6.1.4.4 Medical supplies at 0: Medical can stabilise (stop bleeding, basic first aid) but cannot treat (injuries remain, crew effectiveness stays reduced). Casualties accumulate without recovery.

[ ] 6.1.4.5 Repair materials at 0: Engineering can recalibrate and reroute (minor repairs) but cannot replace components or patch hull breaches (major repairs). Ship degrades over time without ability to recover.

[ ] 6.1.4.6 Drone fuel at 0: No drone launches. Active drones continue until their individual fuel runs out, then are lost.

[ ] 6.1.4.7 Drone parts at 0: Damaged drones cannot be repaired. Destroyed drones cannot be replaced. Flight Ops attrition becomes permanent.

[ ] 6.1.4.8 Ammunition at 0: Marine firepower drops 60%. Boarding defence severely compromised.

[ ] 6.1.4.9 Provisions at 0: Crew morale -2%/min, crew effectiveness -1%/min. After 10 minutes at 0: crew factor across all decks reduced by 20%. After 30 minutes: reduced by 50%. This is a slow death — not immediately fatal but mission-ending over time.

---

## 6.2 VENDOR SYSTEM

### 6.2.1 Vendor Types

Vendors are entities in the game world that the Quartermaster can trade with. Each has an inventory, pricing model, and personality.

[ ] 6.2.1.1 **Space Station (Allied)**: Well-stocked, fair prices, full range of supplies. Base price multiplier: 1.0x. Always willing to trade. Reliable but may not be conveniently located.

[ ] 6.2.1.2 **Space Station (Neutral)**: Moderately stocked, premium prices. Base price multiplier: 1.3x. Willing to trade but impersonal. Prices negotiable. Won't sell military-grade weapons (heavy/nuclear torpedoes) without persuasion.

[ ] 6.2.1.3 **Space Station (Hostile)**: Limited stock, hostile pricing. Base price multiplier: 2.0x. Will only trade if faction standing > -50. Refuses military supplies entirely. May report ship position to hostiles after trade (30% chance).

[ ] 6.2.1.4 **Outpost/Colony**: Small inventory, variable prices. Base price multiplier: 0.8x–1.5x (random per visit). Stocks basics (fuel, provisions, some medical) but rarely has torpedoes or drone parts. Friendly and appreciative of trade — good for reputation building.

[ ] 6.2.1.5 **Merchant Vessel**: Encountered in space. Limited but specialised inventory (carries one or two resource categories in bulk). Base price multiplier: 1.1x. Willing to barter. May offer information as part of a deal. Appears and disappears — time-limited trade window.

[ ] 6.2.1.6 **Black Market Dealer**: Has everything including rare and illegal goods (nuclear torpedoes, experimental tech, cloaking components). Base price multiplier: 2.5x. Cash only (no barter). 15% chance of defective goods (torpedo that doesn't arm, repair materials that fail on first use). No reputation consequences — deals are anonymous. Appears rarely.

[ ] 6.2.1.7 **Salvage Yard**: Buys salvage at fair prices, sells second-hand equipment at discount. Base price multiplier: 0.7x for buying FROM them, 0.9x for selling TO them. Stock is random and often unusual. Good destination after combat with salvage to sell.

[ ] 6.2.1.8 **Allied Warship**: Military vessel willing to transfer supplies. No cost but limited to what they can spare (they keep 60% of their stock). Requires faction standing > 30. Transfer takes time (docking or shuttle, 60s). Excellent source of military supplies but only for allies.

### 6.2.2 Vendor Inventory Generation

[ ] 6.2.2.1 Each vendor type has an inventory template defining which resource categories they stock and quantity ranges. Actual inventory is randomised within ranges when the vendor is spawned.

[ ] 6.2.2.2 Vendor inventory is finite. If the Quartermaster buys all the fuel, it's gone. The vendor doesn't restock during the mission. This prevents infinite resource loops.

[ ] 6.2.2.3 Vendor inventory is revealed progressively. Opening trade shows categories available ("Fuel: Available", "Torpedoes: Available", "Medical: Unavailable"). Actual quantities are revealed during negotiation or by paying for a manifest scan (5% of the item's value, non-refundable).

[ ] 6.2.2.4 Some vendors have hidden inventory — items not listed but available if the Quartermaster asks specifically ("Do you have any nuclear torpedoes?" might reveal a hidden stock at a premium).

### 6.2.3 Pricing Model

[ ] 6.2.3.1 Every resource has a base_price defined globally. This is the "fair market value" in credits.

[ ] 6.2.3.2 Base prices:

| Resource | Base Price Per Unit | Audit |
|----------|-------------------|-------|
| [ ] 6.2.3.2a Fuel (FU) | 2 credits | |
| [ ] 6.2.3.2b Standard torpedo | 15 credits | |
| [ ] 6.2.3.2c Homing torpedo | 30 credits | |
| [ ] 6.2.3.2d Ion torpedo | 30 credits | |
| [ ] 6.2.3.2e Piercing torpedo | 30 credits | |
| [ ] 6.2.3.2f Heavy torpedo | 45 credits | |
| [ ] 6.2.3.2g Proximity torpedo | 30 credits | |
| [ ] 6.2.3.2h Nuclear torpedo | 100 credits | |
| [ ] 6.2.3.2i Experimental torpedo | 60 credits | |
| [ ] 6.2.3.2j Medical supplies (MSU) | 5 credits | |
| [ ] 6.2.3.2k Repair materials (RMU) | 8 credits | |
| [ ] 6.2.3.2l Drone fuel (DFU) | 3 credits | |
| [ ] 6.2.3.2m Drone parts (DPU) | 20 credits | |
| [ ] 6.2.3.2n Ammunition (AMU) | 4 credits | |
| [ ] 6.2.3.2o Provisions (PVU) | 1 credit | |

[ ] 6.2.3.3 Actual price = base_price × vendor_type_multiplier × faction_modifier × urgency_modifier × reputation_modifier × scarcity_modifier.

[ ] 6.2.3.4 Faction modifier: Standing > 50: 0.85x. Standing 20–50: 0.95x. Standing 0–20: 1.0x. Standing -20–0: 1.1x. Standing < -20: 1.3x.

[ ] 6.2.3.5 Urgency modifier: If the ship's stock of the requested resource is below 25%: 1.2x. Below 10%: 1.5x. The vendor can see the ship's condition if docked alongside (visible damage, fuel gauge). The Quartermaster can bluff (see 6.3.4) to hide urgency.

[ ] 6.2.3.6 Reputation modifier: Trade reputation > 50: 0.9x. Reputation 20–50: 0.95x. Reputation 0–20: 1.0x. Reputation < 0: 1.15x.

[ ] 6.2.3.7 Scarcity modifier: If the vendor has less than 30% of their maximum stock of an item: 1.3x (they're running low too). If they have over 80%: 0.9x (surplus, willing to deal).

### 6.2.4 Trade Reputation

[ ] 6.2.4.1 Trade reputation is a ship-wide stat that starts at 0 and ranges from -100 to 100.

[ ] 6.2.4.2 Reputation changes:
- Complete a trade at or above fair price: +2
- Complete a barter both parties agreed to: +1
- Pay for information/manifest scan: +1
- Walk away from a deal politely: 0
- Haggle aggressively but complete trade: -1
- Walk away after vendor made concessions: -3
- Default on an agreement (accept trade then cancel before transfer completes): -10
- Sell defective or misrepresented goods: -15
- Complete escort/delivery side contract: +5
- Vendor reports positive experience to network: +3 (happens at reputation > 30, random 20% chance per trade)

[ ] 6.2.4.3 Reputation is visible to the Quartermaster on their dashboard. Other stations do not see it.

[ ] 6.2.4.4 Reputation persists across vendor interactions within a mission. In multi-mission campaigns (future feature), it persists across missions.

---

## 6.3 NEGOTIATION SYSTEM

### 6.3.1 Trade Channel

[ ] 6.3.1.1 When the ship is within comms range of a vendor, Comms establishes the channel (hail → identify → hand off to Quartermaster). The Quartermaster cannot open trade unilaterally — Comms must establish the link first.

[ ] 6.3.1.2 Once the channel is open, the Quartermaster sees the vendor appear in their "ACTIVE CONTACTS" panel with a [TRADE] button.

[ ] 6.3.1.3 Trade channels have a range limit. Docked: unlimited time. Within 5000 units: stable channel, no time limit. 5000–15000 units: degraded channel (negotiation rounds take 50% longer as messages relay), auto-closes if ship moves beyond 15000. Beyond 15000: channel lost, must re-establish.

[ ] 6.3.1.4 Multiple trade channels can be open simultaneously (e.g., two merchant vessels nearby), but the Quartermaster can only actively negotiate with one at a time.

### 6.3.2 Negotiation Flow

[ ] 6.3.2.1 Opening: Quartermaster clicks [TRADE]. Vendor presents their available categories. Quartermaster selects what they want to buy or sell.

[ ] 6.3.2.2 Offer phase: Vendor presents an opening price (calculated from 6.2.3.3). This is displayed as a price per unit and total for the requested quantity. The Quartermaster sees the offer and can:
- [ACCEPT]: Trade completes at offered price.
- [COUNTER]: Quartermaster proposes a different price. Must be between 50% and 95% of the vendor's offer (lower than 50% is insulting and vendor may break off).
- [BARTER]: Instead of credits, offer goods from cargo. See 6.3.3.
- [WALK AWAY]: Decline the trade. 30% chance vendor calls back with a 10% discount within 15 seconds. Walking away after a callback offer has no further callbacks.
- [INSPECT]: Pay 5% of item value to see exact quantity and quality. Non-refundable.

[ ] 6.3.2.3 Counter-offer round: If the Quartermaster counters, the vendor evaluates:
- Counter within 10% of vendor's price: Vendor accepts.
- Counter within 20%: Vendor meets halfway (splits the difference).
- Counter within 30%: Vendor makes a small concession (5% off original).
- Counter beyond 30%: Vendor holds firm or increases price by 5% ("you're wasting my time").
- Counter below 50%: Vendor breaks off negotiation. Channel remains open but vendor won't discuss that item again for 120 seconds.

[ ] 6.3.2.4 Maximum 3 counter-offer rounds per item. After 3 rounds, vendor gives a final take-it-or-leave-it price.

[ ] 6.3.2.5 Multiple items can be negotiated in sequence within one trade session. Buying multiple categories in one session gives a 5% bundle discount on the second item and 10% on the third.

[ ] 6.3.2.6 Time pressure: If the ship is in combat (shields taking fire, damage alerts), negotiation speed doubles (vendor wants to close fast before the ship is destroyed — or charges more for the urgency). Vendor may also refuse to trade if combat is active ("I'm not docking with a ship under fire").

### 6.3.3 Barter System

[ ] 6.3.3.1 Instead of credits, the Quartermaster can offer items from the ship's cargo hold or surplus resources.

[ ] 6.3.3.2 Barter value of items: Each resource and trade good has a barter value (in credits equivalent). Vendors apply a barter penalty — goods offered in barter are worth 80% of their credit value (the vendor needs margin).

[ ] 6.3.3.3 Information as currency: The Quartermaster can offer decoded intelligence (from Comms), scan data (from Science), or navigation charts (from Helm's explored area). Information value depends on what the vendor cares about:
- Military vendor: values tactical intel and enemy positions (10–50 credits per item)
- Civilian station: values navigation charts and hazard warnings (5–30 credits)
- Merchant: values trade route data and supply/demand intel (15–40 credits)
- Black market: values everything but pays less (50% of normal intel value)

[ ] 6.3.3.4 Services as currency: The Quartermaster can offer the ship's services:
- Escort contract: "We'll escort your convoy for 3 minutes" — vendor provides supplies upfront, Captain must then complete the escort. Failure to complete: -15 reputation, vendor faction standing -10.
- Delivery contract: "We'll deliver this cargo to [destination]" — vendor provides supplies and cargo, ship must reach destination. Cargo occupies cargo space.
- Scan contract: "We'll scan [target] and return the data" — vendor provides supplies, Science must scan the target.
- Patrol contract: "We'll patrol [area] for threats" — vendor provides supplies, ship must patrol waypoints.

[ ] 6.3.3.5 Service contracts appear as missions on the Captain's station after the Quartermaster agrees to terms. The Captain sees "QUARTERMASTER CONTRACT: Escort convoy to waypoint Delta. Deadline: 5 minutes. Penalty for failure: reputation -15."

### 6.3.4 Bluffing and Deception

[ ] 6.3.4.1 The Quartermaster can attempt to bluff during negotiation to hide the ship's true condition:
- [BLUFF: NOT URGENT]: Hide the fact that the resource is critically low. Success: vendor doesn't apply urgency modifier. Failure: vendor applies 1.5x urgency modifier regardless of actual level AND reputation -5 ("you tried to deceive me").
- [BLUFF: MILITARY AUTHORITY]: Claim military requisition authority to get military prices at civilian vendors. Success: prices drop 20%. Failure: vendor refuses to trade entirely for 180 seconds AND reputation -10.
- [BLUFF: COMPETING OFFER]: Claim another vendor nearby is offering a better price. Success: vendor drops price 10%. Failure: vendor holds firm.

[ ] 6.3.4.2 Bluff success chance: base 50%, modified by:
- Trade reputation > 30: +15% (trusted, benefit of the doubt)
- Trade reputation < 0: -20% (known bad actor)
- Comms officer decoded vendor's communications: +20% (know what they know)
- Ship visibly damaged (hull < 50%): -15% for "not urgent" bluffs
- Ship class matches bluff (military ship claiming military authority): +25%

[ ] 6.3.4.3 Bluff outcomes are revealed to the Quartermaster immediately. Other stations don't see bluff attempts or results.

[ ] 6.3.4.4 Maximum 1 bluff per negotiation session. Using a bluff and failing prevents further bluffs with that vendor for the rest of the mission.

---

## 6.4 SHIP CREDITS AND ECONOMY

### 6.4.1 Starting Credits

[ ] 6.4.1.1 Each ship starts with credits determined by ship class and difficulty:

| Ship Class | Base Credits | Audit |
|-----------|-------------|-------|
| [ ] 6.4.1.1a Scout | 300 | |
| [ ] 6.4.1.1b Corvette | 500 | |
| [ ] 6.4.1.1c Frigate | 800 | |
| [ ] 6.4.1.1d Cruiser | 1200 | |
| [ ] 6.4.1.1e Battleship | 1500 | |
| [ ] 6.4.1.1f Carrier | 1000 | |
| [ ] 6.4.1.1g Medical ship | 600 | |

[ ] 6.4.1.2 Difficulty modifier on starting credits: Cadet: 2.0x, Officer: 1.0x, Commander: 0.75x, Admiral: 0.5x.

### 6.4.2 Earning Credits

[ ] 6.4.2.1 Selling trade goods to vendors: credits equal to negotiated price.

[ ] 6.4.2.2 Selling surplus resources: credits equal to negotiated price (selling 50 surplus fuel at 2 credits/unit = 100 credits).

[ ] 6.4.2.3 Selling salvage: credits vary by salvage type and vendor (salvage yards pay best).

[ ] 6.4.2.4 Completing service contracts: credits paid upfront as part of the deal (folded into trade terms — "escort us and we'll give you 200 credits of fuel").

[ ] 6.4.2.5 Mission bounties: Some Comms-generated missions have credit rewards in addition to standing and supplies.

[ ] 6.4.2.6 Selling intelligence: decoded signals, scan data, charts. Priced per 6.3.3.3.

### 6.4.3 Credit Display

[ ] 6.4.3.1 Credits shown on the Quartermaster station dashboard only. Other stations don't see the credit balance.

[ ] 6.4.3.2 Captain can request credit balance via a [RESOURCES] panel that summarises all resource levels and credits. This respects the Captain's need to know the ship's overall status.

---

## 6.5 SALVAGE SYSTEM

### 6.5.1 Salvage Opportunities

[ ] 6.5.1.1 After combat, disabled enemy ships can be salvaged. Science scans the wreck to assess salvage value. The Quartermaster decides what to take.

[ ] 6.5.1.2 Derelict ships encountered during exploration can be salvaged.

[ ] 6.5.1.3 Debris fields (from previous battles, asteroid collisions, etc.) can contain salvageable materials.

### 6.5.2 Salvage Process

[ ] 6.5.2.1 Salvage requires the ship to be within 2000 units of the target and stationary (or very slow, < 10 units/s).

[ ] 6.5.2.2 The Quartermaster selects a target and presses [ASSESS SALVAGE]. Science scan runs automatically (10 seconds). Results show a list of salvageable items with estimated values.

[ ] 6.5.2.3 The Quartermaster selects which items to salvage. Each item has a size (cargo units) and estimated salvage time. Total size must fit in available cargo space.

[ ] 6.5.2.4 [BEGIN SALVAGE] sends an Engineering repair team to the wreck. Salvage time is 30–120 seconds depending on items selected. Team is vulnerable during salvage (if combat resumes, they must be recalled or risk casualties).

[ ] 6.5.2.5 During salvage, a progress bar shows on the Quartermaster and Engineering stations. Engineering can see the repair team's location on the wreck.

[ ] 6.5.2.6 Completed salvage items appear in cargo hold. The Quartermaster can sell them at any vendor.

[ ] 6.5.2.7 Some salvage is directly usable: fuel, torpedoes, medical supplies, repair materials found in wrecks can be transferred directly to ship stores instead of cargo, but at 70% efficiency (damaged/impure). 100 fuel units salvaged = 70 added to fuel tanks.

### 6.5.3 Salvage Risk

[ ] 6.5.3.1 Salvage takes time. More enemies could arrive. The Captain must weigh the value of salvage against the risk of staying stationary.

[ ] 6.5.3.2 Some wrecks are booby-trapped (10% chance). Engineering team takes damage during salvage. Sensor scan quality affects trap detection: if Science did a thorough scan (full resolution), traps are detected before salvage begins. If scan was partial, traps may go undetected.

[ ] 6.5.3.3 Unstable reactor on wreck: 15% chance. Timer starts on proximity (120 seconds). If the ship is within 2000 units when the reactor blows, it takes damage (20–40 hull depending on distance). Science scan detects reactor instability. Quartermaster must decide: rush salvage or abandon.

---

## 6.6 RESOURCE ALLOCATION AND RATIONING

### 6.6.1 Allocation Authority

[ ] 6.6.1.1 The Quartermaster has authority to set consumption limits on any resource category. This is the "rationing" system.

[ ] 6.6.1.2 Rationing levels per resource:
- UNRESTRICTED: Normal consumption, no limits.
- CONSERVE: 75% of normal consumption allowed. Affected systems operate at 90% effectiveness. (e.g., medical treatments take 10% longer, torpedo fire rate limited to 75%)
- RATION: 50% of normal consumption. Affected systems at 75% effectiveness.
- EMERGENCY: 25% of normal consumption. Affected systems at 50% effectiveness. This is severe — crew will feel it immediately.

[ ] 6.6.1.3 Rationing applies immediately when set. Affected stations see a yellow indicator: "FUEL: CONSERVE" or "MEDICAL SUPPLIES: RATIONED".

[ ] 6.6.1.4 Captain can override Quartermaster rationing with [OVERRIDE RATION] on the Captain's resource panel. This removes the restriction and creates a log entry: "Captain overrode Quartermaster fuel ration." The Quartermaster sees the override notification.

[ ] 6.6.1.5 Rationing does NOT apply to emergency actions. Emergency reactor operations, life-saving medical treatment, and last-resort defence actions bypass rationing. Rationing limits sustained consumption, not crisis response.

### 6.6.2 Allocation Requests

[ ] 6.6.2.1 Other stations can request resources from the Quartermaster:
- Engineering: "Request 20 RMU for reactor coolant replacement" → appears on Quartermaster as allocation request with approve/deny buttons
- Medical: "Request 15 MSU for mass casualty treatment" → same
- Flight Ops: "Request drone replacement (5 DPU)" → same
- Security: "Request ammunition resupply (20 AMU)" → same
- Weapons: "Request torpedo reload from cargo" → only if surplus torpedoes are in cargo

[ ] 6.6.2.2 The Quartermaster sees requests in a queue. Each shows: requesting station, resource type, quantity, current stock level, and estimated impact ("Approving depletes repair materials to 40%").

[ ] 6.6.2.3 Quartermaster approves or denies. Denial sends a notification to the requesting station: "Quartermaster denied: insufficient stock" or the Quartermaster types a brief reason.

[ ] 6.6.2.4 If the Quartermaster station is uncrewed, requests auto-approve if stock is above 50% of the requested resource. Below 50%, requests queue until the station is crewed.

### 6.6.3 Forecasting

[ ] 6.6.3.1 The Quartermaster dashboard shows estimated time to depletion for each resource based on current burn rate. This updates every 10 seconds.

[ ] 6.6.3.2 Burn rate is calculated from the average consumption over the last 60 seconds, smoothed to avoid spikes from single events.

[ ] 6.6.3.3 Forecast display format: "FUEL: 847 FU | Burn: 1.2 FU/s | Depleted in: 11m 47s"

[ ] 6.6.3.4 Forecast includes projected state at next known vendor: "At current consumption, arriving at Station Alpha in 8 minutes with: FUEL 271 FU (23%), MEDICAL 45 MSU (56%)..." This requires Helm waypoint data — if no waypoint is set, this projection is not shown.

[ ] 6.6.3.5 Colour coding: Green (>50%), Amber (25–50%), Red (<25%), Flashing Red (<10%).

---

## 6.7 QUARTERMASTER CLIENT UI

### 6.7.1 Layout Overview

[ ] 6.7.1.1 Three-panel layout consistent with other stations.

[ ] 6.7.1.2 **Left panel: RESOURCE DASHBOARD** — all resource levels, burn rates, depletion forecasts, rationing controls, cargo manifest.

[ ] 6.7.1.3 **Centre panel: TRADE INTERFACE** — active negotiation dialogue, vendor inventory, offer/counter-offer controls, barter selection, bluff options. When no trade is active, shows vendor proximity list and market intelligence.

[ ] 6.7.1.4 **Right panel: ALLOCATION & INTEL** — allocation request queue, completed trade log, trade reputation, vendor relationship summary, mission contracts accepted.

[ ] 6.7.1.5 **Bottom bar**: Credits display, cargo space (used/total), trade reputation score, active ration indicators.

### 6.7.2 Resource Dashboard (Left Panel)

[ ] 6.7.2.1 Resource bars for each of the 8 resource types. Each bar shows: icon, name, current/capacity, bar fill with colour coding (green/amber/red), burn rate, estimated depletion time.

[ ] 6.7.2.2 Clicking a resource bar expands it to show: consumption breakdown by station ("Engineering: 0.8 RMU/min, Medical: 0 RMU/min"), historical graph (last 5 minutes of consumption), rationing control dropdown.

[ ] 6.7.2.3 Cargo manifest section below resource bars. List of items in cargo with name, size, estimated value. [JETTISON] button per item to free cargo space in emergencies (item lost permanently). Jettison requires confirmation dialogue.

[ ] 6.7.2.4 Summary line: "Ship status: COMFORTABLE / STRAINED / CRITICAL" based on overall resource health. COMFORTABLE: all resources > 50%. STRAINED: any resource 25–50%. CRITICAL: any resource < 25%.

### 6.7.3 Trade Interface (Centre Panel)

[ ] 6.7.3.1 When no trade is active: shows a list of known vendors within sensor range with distance, type, faction standing, and [HAIL] button (which sends a request to Comms to establish channel). Below: "market intel" — a scrolling feed of trade-relevant information from Comms intercepts and previous trades ("Station Alpha fuel prices trending up", "Merchant vessel carrying medical supplies detected at bearing 045").

[ ] 6.7.3.2 When trade is active: shows the negotiation interface. Top: vendor name, type, faction, distance, channel quality. Middle: conversation thread (vendor offers, Quartermaster responses, outcomes). Each vendor message has a portrait or icon (station logo, merchant ship silhouette, etc.). Bottom: action buttons contextual to negotiation phase ([ACCEPT], [COUNTER], [BARTER], [WALK AWAY], [INSPECT], [BLUFF] dropdown).

[ ] 6.7.3.3 Counter-offer UI: slider showing vendor's price and Quartermaster's counter. Visual indicator showing likely vendor response zones (green: will accept, amber: will negotiate, red: will refuse).

[ ] 6.7.3.4 Barter UI: two-column layout. Left column: "YOUR OFFER" — dragable items from cargo and surplus resources. Right column: "VENDOR OFFERS" — items the vendor has. Balance indicator in the middle showing whether the barter is fair (green), tilted toward vendor (amber), or insulting (red).

[ ] 6.7.3.5 Service contract UI: shows contract terms with clear obligations, deadline, reward, and penalty. [ACCEPT CONTRACT] and [DECLINE] buttons. Accepted contracts move to the right panel's mission log.

### 6.7.4 Allocation & Intel (Right Panel)

[ ] 6.7.4.1 Allocation request queue: list of pending requests from other stations. Each shows: requesting station icon, resource type, quantity, time of request, current stock impact preview. [APPROVE] and [DENY] buttons. [DENY] opens a brief text input for reason.

[ ] 6.7.4.2 Trade log: chronological list of completed trades. Each entry: timestamp, vendor, items bought/sold, price paid, reputation change. Scrollable.

[ ] 6.7.4.3 Trade reputation display: numerical value with descriptor (e.g., "47 — RESPECTED") and trend arrow (up/down/stable over last 3 trades).

[ ] 6.7.4.4 Vendor relationship summary: list of all vendors encountered this mission, each showing faction, standing, last trade outcome, and whether they're still in range.

[ ] 6.7.4.5 Active contracts: list of accepted service contracts with objective, deadline countdown, and status (in progress / completed / failed).

### 6.7.5 Audio

[ ] 6.7.5.1 Trade channel open: comms-style hail tone.
[ ] 6.7.5.2 Vendor offer received: subtle notification chime.
[ ] 6.7.5.3 Trade completed: cash register sound (satisfying, brief).
[ ] 6.7.5.4 Trade failed / vendor broke off: low negative tone.
[ ] 6.7.5.5 Bluff succeeded: subtle positive tone.
[ ] 6.7.5.6 Bluff failed: warning buzz.
[ ] 6.7.5.7 Resource warning (25%): amber alert tone (once).
[ ] 6.7.5.8 Resource critical (10%): red alert tone (repeating until acknowledged).
[ ] 6.7.5.9 Allocation request received: incoming message ping.
[ ] 6.7.5.10 Salvage complete: positive chime.
[ ] 6.7.5.11 Contract deadline approaching (30s remaining): ticking clock.

---

## 6.8 CROSS-STATION INTEGRATION

### 6.8.1 Quartermaster ↔ Comms

[ ] 6.8.1.1 Comms establishes trade channels. Quartermaster cannot open trade without Comms first hailing the vendor.

[ ] 6.8.1.2 Comms decoded intel about vendor prices, supply levels, or black market locations appears as market intelligence on the Quartermaster's trade panel.

[ ] 6.8.1.3 Comms-generated trade/merchant hail missions are presented to both Comms (for mission offer flow) and Quartermaster (for trade opportunity awareness).

[ ] 6.8.1.4 Comms faction standing directly affects trade pricing (6.2.3.4).

### 6.8.2 Quartermaster ↔ Science

[ ] 6.8.2.1 Science scan data is tradeable. When Science completes a detailed scan, the Quartermaster is notified: "New scan data available for trade: [target] — estimated value: [X] credits."

[ ] 6.8.2.2 Science wreck scans provide salvage assessment data to the Quartermaster (6.5.2.2).

[ ] 6.8.2.3 Science can scan a vendor's cargo from range (15000 units) to reveal their inventory before hailing. Takes 30 seconds. Not all vendors appreciate being scanned uninvited (may increase opening prices by 10%).

### 6.8.3 Quartermaster ↔ Engineering

[ ] 6.8.3.1 Engineering repair material requests go through the allocation system (6.6.2.1).

[ ] 6.8.3.2 Major repairs show projected material cost on the Engineering station: "Hull breach repair: estimated 8 RMU" so Engineering knows before requesting.

[ ] 6.8.3.3 Engineering salvage teams are dispatched through Engineering's repair team system (6.5.2.4). The Quartermaster initiates, Engineering executes.

[ ] 6.8.3.4 Fuel consumption rate from Engineering's power management directly feeds the Quartermaster's forecasting.

### 6.8.4 Quartermaster ↔ Weapons

[ ] 6.8.4.1 Torpedo consumption feeds Quartermaster tracking. Each torpedo fired decrements the torpedo count and updates burn rate calculation.

[ ] 6.8.4.2 If torpedoes are rationed, Weapons fire rate is limited accordingly (6.6.1.2).

[ ] 6.8.4.3 Weapons can see current torpedo stock and rationing status on their station.

### 6.8.5 Quartermaster ↔ Medical

[ ] 6.8.5.1 Medical supply consumption feeds Quartermaster tracking. Each treatment decrements supplies.

[ ] 6.8.5.2 If medical supplies are rationed, treatment times increase (6.6.1.2).

[ ] 6.8.5.3 Medical can see current supply level and rationing status on their station.

### 6.8.6 Quartermaster ↔ Flight Ops

[ ] 6.8.6.1 Drone fuel and parts consumption feeds Quartermaster tracking.

[ ] 6.8.6.2 Drone replacement requests go through allocation system.

[ ] 6.8.6.3 If drone fuel is rationed, Flight Ops is limited in active drone count (fewer simultaneous drones).

### 6.8.7 Quartermaster ↔ Security

[ ] 6.8.7.1 Ammunition consumption during boarding feeds Quartermaster tracking.

[ ] 6.8.7.2 Ammo resupply requests go through allocation system.

### 6.8.8 Quartermaster ↔ Captain

[ ] 6.8.8.1 Captain sees a [RESOURCES] summary panel showing all resource levels and credit balance — a read-only view of the Quartermaster's dashboard.

[ ] 6.8.8.2 Captain can override rationing (6.6.1.4).

[ ] 6.8.8.3 Service contracts accepted by the Quartermaster appear as missions on the Captain's station.

[ ] 6.8.8.4 Quartermaster resupply recommendations ("Recommend docking at Station Alpha for fuel") appear as advisory messages on the Captain's station.

### 6.8.9 Quartermaster ↔ Helm

[ ] 6.8.9.1 Helm waypoint data feeds the Quartermaster's projected-state-at-destination forecast (6.6.3.4).

[ ] 6.8.9.2 Known vendor positions appear as optional waypoint markers on Helm's navigation display, labelled with vendor type.

---

## 6.9 THE JANITOR INTEGRATION

[ ] 6.9.1 "Restock coffee" Janitor action now actually depletes 1 PVU from provisions (provisions reduced by 1, crew factor boost still applies). If provisions are rationed, the action is blocked with flavour text: "NOTICE: Coffee has been rationed by the Quartermaster. The Janitor is displeased."

[ ] 6.9.2 "Restock snacks" similarly costs 1 PVU.

[ ] 6.9.3 "The Secret Stash" can now yield 50 credits as one of the random outcomes (in addition to existing possibilities).

[ ] 6.9.4 New Janitor task: "Inventory Audit" — checks cargo hold for errors. Effect: reveals any defective goods from black market purchases (they glow red in the cargo manifest for 120 seconds). Flavour text: "The Janitor has found some suspicious items. They smell wrong. Trust the nose." Cooldown: 300 seconds.

[ ] 6.9.5 New Janitor sticky note when provisions drop below 25%: "To whom it may concern: the coffee is GONE. I cannot work under these conditions. This is a HOSTILE work environment. — The Janitor"

---

## 6.10 TEST TARGETS

| Test File | Target | Audit |
|-----------|--------|-------|
| [ ] 6.10.1 tests/test_consumables.py | 40+ tests (all 8 resource types, depletion, consequences, per ship class starting values) | |
| [ ] 6.10.2 tests/test_vendors.py | 30+ tests (vendor types, inventory generation, pricing model, all modifiers) | |
| [ ] 6.10.3 tests/test_negotiation.py | 35+ tests (offer/counter/accept/walk-away flow, barter, bluffing, time pressure, service contracts) | |
| [ ] 6.10.4 tests/test_economy.py | 20+ tests (credits, earning, spending, difficulty modifier) | |
| [ ] 6.10.5 tests/test_salvage.py | 20+ tests (assess, collect, risks, direct-use transfer, cargo space) | |
| [ ] 6.10.6 tests/test_rationing.py | 25+ tests (all levels, all resources, effectiveness reduction, captain override, emergency bypass) | |
| [ ] 6.10.7 tests/test_allocation.py | 20+ tests (request flow, approve/deny, auto-approve when uncrewed, queue) | |
| [ ] 6.10.8 tests/test_forecasting.py | 15+ tests (burn rate calculation, depletion estimates, projected state at destination) | |
| [ ] 6.10.9 tests/test_quartermaster_integration.py | 30+ tests (all cross-station interactions from 6.8) | |
| Total | 235+ new tests | |

---

## BUILD ORDER

| Part | Sections | Description | Risk | Depends On |
|------|----------|-------------|------|------------|
| 6.1 | 6.1.1–6.1.4 | Consumable resource system | Medium | Ship class JSON (Phase 1) |
| 6.2 | 6.2.1–6.2.4 | Vendor system | Medium | 6.1 |
| 6.3 | 6.3.1–6.3.4 | Negotiation system | High | 6.2, Comms station |
| 6.4 | 6.4.1–6.4.3 | Credits and economy | Low | 6.2 |
| 6.5 | 6.5.1–6.5.3 | Salvage system | Medium | 6.1, Science, Engineering |
| 6.6 | 6.6.1–6.6.3 | Rationing and allocation | Medium | 6.1, all stations |
| 6.7 | 6.7.1–6.7.5 | Client UI | Medium | 6.1–6.6 |
| 6.8 | 6.8.1–6.8.9 | Cross-station integration | High | All stations, 6.1–6.7 |
| 6.9 | 6.9.1–6.9.5 | Janitor integration | Low | Janitor station, 6.1 |
| 6.10 | 6.10.1–6.10.9 | Tests | Medium | 6.1–6.9 |

**Commit after each part.** Format: "v0.07-6.X: description"

---

## STOP CONDITIONS

- Resource depletion makes the game unplayable within the first 5 minutes on any ship class at Officer difficulty (balance problem)
- Negotiation system creates server lag from too many concurrent price calculations
- Rationing reduces station effectiveness so much that affected stations become unfun to play
- Trade channel handoff between Comms and Quartermaster is confusing or unreliable
- Allocation request queue floods the Quartermaster during heavy combat (need rate limiting or auto-approve threshold)
- Credit economy is trivially exploitable (buy low at one vendor, sell high at another in a loop)
- Salvage risk/reward ratio makes salvage either always-do or never-do instead of a genuine decision

---

## CLASSROOM NOTES

The Quartermaster role is ideal for students who:
- Are less interested in combat but want a critical role
- Enjoy strategy, planning, and negotiation
- Want to develop supply chain and resource management thinking
- Like being the communication hub between stations

On smaller crews (2–4 players), the Quartermaster can be combined with another low-activity station (the same player handles both). On larger crews (10+), the Quartermaster is a full-time role — there's always something to manage, negotiate, or plan.

The Quartermaster naturally creates inter-station communication, which is the core pedagogical tool of Starbridge. Every station has a reason to talk to the Quartermaster, and the Quartermaster has a reason to talk to every station.

---

*End of Phase 6 Specification*
*Total audit checkboxes: 198*
*Total test target: 235+ new tests*
