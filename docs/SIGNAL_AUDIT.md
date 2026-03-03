# Starbridge Signal Audit Report

**Generated:** 2026-03-03
**Codebase Version:** v0.08-polish (6609 tests, commit ecbb4c5)
**Scope:** All 13 stations, server + client, cross-cutting systems

---

## Table of Contents

1. [Signal Registry (per station)](#1-signal-registry)
2. [Connectivity Matrix (13x13)](#2-connectivity-matrix)
3. [Dead Signal Report](#3-dead-signal-report)
4. [Orphan Handler Report](#4-orphan-handler-report)
5. [Key Mismatch Report](#5-key-mismatch-report)
6. [Shared State Audit](#6-shared-state-audit)
7. [Client-Side Signal Check](#7-client-side-signal-check)
8. [Summary Statistics](#8-summary-statistics)

---

## 1. Signal Registry

### CAPTAIN

#### EMITS (server broadcasts received by captain client)

| Signal Key | Source File | Target Roles |
|---|---|---|
| `ship.state` | game_loop.py:1747 | ALL |
| `ship.alert_changed` | captain.py:119 | ALL |
| `ship.hull_hit` | game_loop.py:2057 | ALL |
| `ship.system_damaged` | game_loop.py:1545 | ALL |
| `world.entities` | game_loop.py:1748 | helm, engineering, captain, viewscreen |
| `captain.override_changed` | captain.py:134 | ALL |
| `captain.log_entry` | captain.py (via queue) | captain |
| `captain.authorization_request` | game_loop.py (weapons nuclear) | captain |
| `weapons.authorization_result` | game_loop.py | captain |
| `weapons.auto_fire_status` | game_loop.py:1201 | captain |
| `science.scan_progress` | game_loop.py:1862 | ALL |
| `science.scan_complete` | game_loop.py:1910 | ALL |
| `mission.objective_update` | game_loop.py:1306 | ALL |
| `mission.dynamic_list` | game_loop.py:1821 | captain |
| `mission.mission_offered` | game_loop.py:1813 | captain, comms |
| `mission.mission_accepted` | game_loop.py:1813 | captain, comms |
| `mission.mission_declined` | game_loop.py:1813 | captain, comms |
| `mission.mission_completed` | game_loop.py:1813 | captain, comms |
| `mission.mission_failed` | game_loop.py:1813 | captain, comms |
| `mission.mission_expired` | game_loop.py:1813 | captain, comms |
| `mission.objective_completed` | game_loop.py:1813 | captain, comms |
| `crew.roster` | game_loop.py:2011 | ALL |
| `comms.contacts` | game_loop.py:1784 | captain (role-filtered) |
| `comms.contact_merged` | game_loop.py:1774 | captain, helm, science, weapons |
| `operations.overlay` | game_loop.py:2197 | helm, captain, weapons |
| `operations.intel_analysis` | game_loop.py:2203 | captain |
| `map.sector_grid` | game_loop.py:2465 | captain, helm, science, ops, comms, flight_ops |
| `map.scan_indicator` | game_loop.py:1878 | captain, helm |
| `docking.complete` | game_loop_docking.py | captain |
| `docking.undocked` | game_loop_docking.py | captain |
| `docking.service_complete` | game_loop_docking.py | captain |
| `game.started` | main.py:779 | ALL |
| `game.saved` | captain.py:184 | ALL |
| `game.over` | game_loop.py:1351 | ALL |

#### EXPECTS (messages captain client sends to server)

| Signal Key | Client File:Line | Handler |
|---|---|---|
| `captain.set_alert` | captain.js:211 | captain.py |
| `captain.set_general_order` | captain.js:216 | captain.py → queue |
| `captain.system_override` | captain.js:357 | captain.py |
| `captain.set_priority_target` | captain.js:389 | captain.py → queue |
| `captain.accept_mission` | captain.js:270 | captain.py → queue |
| `captain.decline_mission` | captain.js:275 | captain.py → queue |
| `captain.undock` | captain.js:281 | captain.py → queue |
| `captain.authorize` | captain.js:959 | captain.py → queue |
| `captain.add_log` | captain.js:994 | captain.py → queue |
| `captain.save_game` | captain.js:1021 | captain.py |
| `captain.acknowledge_all_stop` | captain.js:155 | captain.py → queue |
| `map.plot_route` | captain.js:394 | queue forward |

---

### HELM

#### EMITS (server broadcasts received by helm client)

| Signal Key | Source File | Target Roles |
|---|---|---|
| `ship.state` | game_loop.py:1747 | ALL |
| `ship.alert_changed` | captain.py:119 | ALL |
| `ship.hull_hit` | game_loop.py:2057 | ALL |
| `world.entities` | game_loop.py:1748 | helm, engineering, captain, viewscreen |
| `weapons.beam_fired` | game_loop.py | ALL |
| `map.sector_grid` | game_loop.py:2465 | captain, helm, science, ops, comms, flight_ops |
| `map.scan_indicator` | game_loop.py:1878 | captain, helm |
| `docking.approach_info` | game_loop_docking.py | helm |
| `docking.complete` | game_loop_docking.py | helm |
| `docking.undocked` | game_loop_docking.py | helm |
| `comms.contacts` | game_loop.py:1784 | helm (role-filtered) |
| `operations.overlay` | game_loop.py:2197 | helm, captain, weapons |
| `game.started` | main.py:779 | ALL |
| `game.over` | game_loop.py:1351 | ALL |

#### EXPECTS (messages helm client sends to server)

| Signal Key | Client File:Line | Handler |
|---|---|---|
| `helm.set_heading` | helm.js:745 | helm.py → queue |
| `helm.set_throttle` | helm.js:720 | helm.py → queue |
| `map.plot_route` | helm.js:248 | queue forward |
| `captain.acknowledge_all_stop` | helm.js:155 | captain.py → queue |

---

### WEAPONS

#### EMITS (server broadcasts received by weapons client)

| Signal Key | Source File | Target Roles |
|---|---|---|
| `ship.state` | game_loop.py:1747 | ALL |
| `ship.alert_changed` | captain.py:119 | ALL |
| `ship.hull_hit` | game_loop.py:2057 | ALL |
| `ship.system_damaged` | game_loop.py:1545 | ALL |
| `sensor.contacts` | game_loop.py:1761 | weapons, science, flight_ops, operations |
| `weapons.beam_fired` | game_loop.py | ALL |
| `weapons.torpedo_hit` | game_loop.py:2361 | ALL |
| `weapons.torpedo_fired` | game_loop.py | ALL |
| `weapons.tube_loading` | game_loop.py | weapons |
| `weapons.tube_loaded` | game_loop.py | weapons |
| `weapons.targeting_denied` | game_loop.py:1241 | weapons |
| `weapons.diplomatic_incident` | game_loop.py:1236 | ALL |
| `captain.authorization_request` | game_loop.py | captain, weapons |
| `weapons.authorization_result` | game_loop.py | captain, weapons |
| `comms.contacts` | game_loop.py:1784 | weapons (role-filtered) |
| `game.started` | main.py:779 | ALL |
| `game.over` | game_loop.py:1351 | ALL |

#### EXPECTS (messages weapons client sends to server)

| Signal Key | Client File:Line | Handler |
|---|---|---|
| `weapons.fire_beams` | weapons.js:528 | weapons.py → queue |
| `weapons.fire_torpedo` | weapons.js:551 | weapons.py → queue |
| `weapons.load_tube` | weapons.js:658 | weapons.py → queue |
| `weapons.select_target` | weapons.js:671 | weapons.py → queue |
| `weapons.set_shield_focus` | weapons.js:791 | weapons.py → queue |

---

### ENGINEERING

#### EMITS (server broadcasts received by engineering client)

| Signal Key | Source File | Target Roles |
|---|---|---|
| `ship.state` | game_loop.py:1747 | ALL |
| `ship.alert_changed` | captain.py:119 | ALL |
| `ship.hull_hit` | game_loop.py:2057 | ALL |
| `ship.system_damaged` | game_loop.py:1545 | ALL |
| `world.entities` | game_loop.py:1748 | helm, engineering, captain, viewscreen |
| `engineering.state` | game_loop.py:2113 | engineering |
| `engineering.dc_state` | game_loop.py:2075 | engineering, hazard_control |
| `captain.override_changed` | captain.py:134 | ALL |
| `puzzle.assist_available` | game_loop.py:1180 | engineering |
| `puzzle.assist_sent` | game_loop.py | engineering |
| `game.started` | main.py:779 | ALL |
| `game.over` | game_loop.py:1351 | ALL |

#### EXPECTS (messages engineering client sends to server)

| Signal Key | Client File:Line | Handler |
|---|---|---|
| `engineering.set_power` | engineering.js:520 | engineering.py → queue |
| `engineering.set_repair` | engineering.js:666 | engineering.py → queue |
| `engineering.dispatch_team` | engineering.js:814 | engineering.py → queue |
| `engineering.recall_team` | engineering.js:890 | engineering.py → queue |
| `engineering.request_escort` | engineering.js:900 | engineering.py → queue |
| `engineering.cancel_repair_order` | engineering.js:936 | engineering.py → queue |
| `engineering.set_battery_mode` | engineering.js:977 | engineering.py → queue |
| `engineering.dispatch_dct` | engineering.js (comment) | game_loop.py:2579 |
| `engineering.cancel_dct` | engineering.js (comment) | game_loop.py:2583 |

---

### SCIENCE

#### EMITS (server broadcasts received by science client)

| Signal Key | Source File | Target Roles |
|---|---|---|
| `ship.state` | game_loop.py:1747 | ALL |
| `ship.alert_changed` | captain.py:119 | ALL |
| `ship.hull_hit` | game_loop.py:2057 | ALL |
| `sensor.contacts` | game_loop.py:1761 | weapons, science, flight_ops, operations |
| `science.scan_progress` | game_loop.py:1862 | ALL |
| `science.scan_complete` | game_loop.py:1910 | ALL |
| `science.sector_scan_progress` | game_loop.py:1872 | science |
| `science.sector_scan_complete` | game_loop.py:1884 | science, captain, helm |
| `science.scan_interrupted` | game_loop.py:1898 | science, captain |
| `mission.signal_bearing` | game_loop_mission.py:201 | ALL |
| `comms.contacts` | game_loop.py:1784 | science (role-filtered) |
| `game.started` | main.py:779 | ALL |
| `game.over` | game_loop.py:1351 | ALL |

#### EXPECTS (messages science client sends to server)

| Signal Key | Client File:Line | Handler |
|---|---|---|
| `science.start_scan` | science.js:537 | game_loop.py:2831 |
| `science.cancel_scan` | science.js:563 | game_loop.py:2840 |
| `science.start_sector_scan` | science.js:523 | game_loop.py:2842 |
| `science.cancel_sector_scan` | science.js:554 | game_loop.py:2859 |
| `science.scan_interrupt_response` | science.js:573 | game_loop.py:2862 |

---

### MEDICAL

#### EMITS (server broadcasts received by medical client)

| Signal Key | Source File | Target Roles |
|---|---|---|
| `ship.state` | game_loop.py:1747 | ALL |
| `ship.alert_changed` | captain.py:119 | ALL |
| `ship.hull_hit` | game_loop.py:2057 | ALL |
| `medical.state` | game_loop.py:1991 | medical |
| `medical.crew_roster` | game_loop.py:2006 | medical |
| `medical.event` | game_loop.py:2015 | medical |
| `game.started` | main.py:779 | ALL |
| `game.over` | game_loop.py:1351 | ALL |

#### EXPECTS (messages medical client sends to server)

| Signal Key | Client File:Line | Handler |
|---|---|---|
| `medical.admit` | medical.js:879 | game_loop.py:2873 |
| `medical.treat` | medical.js:821 | game_loop.py:2876 |
| `medical.stabilise` | medical.js:823 | game_loop.py:2879 |
| `medical.discharge` | medical.js:885 | game_loop.py:2882 |
| `medical.quarantine` | medical.js:891 | game_loop.py:2885 |

---

### SECURITY

#### EMITS (server broadcasts received by security client)

| Signal Key | Source File | Target Roles |
|---|---|---|
| `ship.alert_changed` | captain.py:119 | ALL |
| `ship.hull_hit` | game_loop.py:2057 | ALL |
| `security.interior_state` | game_loop.py:1920 | security |
| `security.incident` | game_loop.py:1601 | security |
| `game.started` | main.py:779 | ALL |
| `game.over` | game_loop.py:1351 | ALL |

#### EXPECTS (messages security client sends to server)

| Signal Key | Client File:Line | Handler |
|---|---|---|
| `security.send_team` | security.js:699 | game_loop.py:2900 |
| `security.move_squad` | security.js:707 | game_loop.py:2891 |
| `security.disengage_team` | security.js:564 | game_loop.py:2909 |
| `security.station_team` | security.js:578 | game_loop.py:2906 |
| `security.lock_door` | security.js:723 | game_loop.py:2916 |
| `security.unlock_door` | security.js:727 | game_loop.py:2919 |
| `security.lockdown_deck` | security.js:734 | game_loop.py:2922 |
| `security.lift_lockdown` | security.js:738 | game_loop.py:2925 |
| `security.seal_bulkhead` | security.js:747 | game_loop.py:2932 |
| `security.unseal_bulkhead` | security.js:748 | game_loop.py:2935 |
| `security.set_deck_alert` | security.js:496 | game_loop.py:2938 |
| `security.arm_crew` | security.js:755 | game_loop.py:2941 |
| `security.disarm_crew` | security.js:756 | game_loop.py:2944 |
| `security.quarantine_room` | security.js:760 | game_loop.py:2947 |
| `security.lift_quarantine` | security.js:761 | game_loop.py:2950 |

---

### COMMS

#### EMITS (server broadcasts received by comms client)

| Signal Key | Source File | Target Roles |
|---|---|---|
| `ship.state` | game_loop.py:1747 | ALL |
| `ship.alert_changed` | captain.py:119 | ALL |
| `ship.hull_hit` | game_loop.py:2057 | ALL |
| `comms.state` | game_loop.py:1938 | comms |
| `comms.npc_response` | game_loop.py:1943 | comms |
| `comms.incoming_transmission` | game_loop.py:1640 | comms |
| `comms.distress_signal` | game_loop.py:1711 | comms, helm, captain |
| `comms.distress_assessment` | game_loop.py:3014 | comms |
| `puzzle.assist_available` | game_loop.py:1184 | comms |
| `docking.approach_info` | game_loop_docking.py | comms |
| `docking.clearance_granted` | game_loop_docking.py | comms |
| `docking.clearance_denied` | game_loop_docking.py | comms |
| `game.started` | main.py:779 | ALL |
| `game.over` | game_loop.py:1351 | ALL |

#### EXPECTS (messages comms client sends to server)

| Signal Key | Client File:Line | Handler |
|---|---|---|
| `comms.tune_frequency` | comms.js:159 | game_loop.py:2982 |
| `comms.hail` | comms.js:166 | game_loop.py:2985 |
| `comms.decode_signal` | comms.js:409 | game_loop.py:2992 |
| `comms.respond` | comms.js:496 | game_loop.py:2995 |
| `comms.route_intel` | comms.js:442 | game_loop.py:3003 |
| `comms.set_channel` | comms.js:556 | game_loop.py:3005 |
| `comms.dismiss_signal` | comms.js:418 | game_loop.py |
| `comms.assess_distress` | comms.js:416 | game_loop.py |
| `creature.set_comm_progress` | comms.js:673 | queue forward |
| `docking.request_clearance` | comms.js:712 | queue forward |

---

### ELECTRONIC WARFARE

#### EMITS (server broadcasts received by EW client)

| Signal Key | Source File | Target Roles |
|---|---|---|
| `ship.state` | game_loop.py:1747 | ALL |
| `ship.alert_changed` | captain.py:119 | ALL |
| `ship.hull_hit` | game_loop.py:2057 | ALL |
| `ew.state` | game_loop.py:2181 | electronic_warfare |
| `game.started` | main.py:779 | ALL |
| `game.over` | game_loop.py:1351 | ALL |

#### EXPECTS (messages EW client sends to server)

| Signal Key | Client File:Line | Handler |
|---|---|---|
| `ew.set_jam_target` | ew.js:286 | game_loop.py:3068 |
| `ew.toggle_countermeasures` | ew.js:94 | game_loop.py:3072 |
| `ew.begin_intrusion` | ew.js:101 | game_loop.py:3077 |
| `creature.sedate` | ew.js:346 | queue forward |
| `creature.ew_disrupt` | ew.js:351 | queue forward |

---

### FLIGHT OPS

#### EMITS (server broadcasts received by flight_ops client)

| Signal Key | Source File | Target Roles |
|---|---|---|
| `ship.state` | game_loop.py:1747 | ALL |
| `ship.alert_changed` | captain.py:119 | ALL |
| `ship.hull_hit` | game_loop.py:2057 | ALL |
| `sensor.contacts` | game_loop.py:1761 | weapons, science, flight_ops, operations |
| `flight_ops.state` | game_loop.py:2121 | flight_ops |
| `flight_ops.events` | game_loop.py:2135 | flight_ops |
| `game.started` | main.py:779 | ALL |
| `game.over` | game_loop.py:1351 | ALL |

#### EXPECTS (messages flight_ops client sends to server)

| Signal Key | Client File:Line | Handler |
|---|---|---|
| `flight_ops.launch_drone` | flight_ops.js:1338 | game_loop.py:3031 |
| `flight_ops.recall_drone` | flight_ops.js:1193 | game_loop.py:3035 |
| `flight_ops.set_waypoint` | flight_ops.js:727 | game_loop.py:3039 |
| `flight_ops.set_loiter_point` | flight_ops.js:777 | game_loop.py:3041 |
| `flight_ops.set_waypoints` | flight_ops.js:951 | game_loop.py:3042 |
| `flight_ops.set_engagement_rules` | flight_ops.js:1199 | game_loop.py:3046 |
| `flight_ops.designate_target` | flight_ops.js:764 | game_loop.py:3050 |
| `flight_ops.deploy_decoy` | flight_ops.js:746 | game_loop.py:3052 |
| `flight_ops.deploy_buoy` | flight_ops.js:865 | game_loop.py:3055 |
| `flight_ops.clear_to_land` | flight_ops.js:1644 | game_loop.py:3059 |
| `flight_ops.rush_turnaround` | flight_ops.js:1386 | game_loop.py:3061 |
| `flight_ops.cancel_launch` | flight_ops.js:1224 | game_loop.py:3065 |

---

### OPERATIONS

#### EMITS (server broadcasts received by operations client)

| Signal Key | Source File | Target Roles |
|---|---|---|
| `ship.state` | game_loop.py:1747 | ALL |
| `ship.alert_changed` | captain.py:119 | ALL |
| `sensor.contacts` | game_loop.py:1761 | weapons, science, flight_ops, operations |
| `operations.state` | game_loop.py:2187 | operations |
| `operations.event` | game_loop.py:2192 | dynamic roles |
| `game.started` | main.py:779 | ALL |
| `game.over` | game_loop.py:1351 | ALL |

#### EXPECTS (messages operations client sends to server)

| Signal Key | Client File:Line | Handler |
|---|---|---|
| `operations.start_assessment` | operations.js:476 | game_loop.py:3114 |
| `operations.set_threat_level` | operations.js:563 | game_loop.py:3129 |
| `operations.mark_objective` | operations.js:653 | game_loop.py:3150 |
| `operations.station_advisory` | operations.js:707 | game_loop.py:3153 |

---

### HAZARD CONTROL

#### EMITS (server broadcasts received by hazard_control client)

| Signal Key | Source File | Target Roles |
|---|---|---|
| `ship.state` | game_loop.py:1747 | ALL |
| `ship.alert_changed` | captain.py:119 | ALL |
| `ship.hull_hit` | game_loop.py:2057 | ALL |
| `hazard_control.state` | game_loop.py:2079 | hazard_control |
| `hazard_control.atmosphere` | game_loop.py:2086 | hazard_control |
| `game.started` | main.py:779 | ALL |
| `game.over` | game_loop.py:1351 | ALL |

#### EXPECTS (messages hazard_control client sends to server)

| Signal Key | Client File:Line | Handler |
|---|---|---|
| `hazard_control.suppress_local` | hazard_control.js:747 | game_loop.py:2586 |
| `hazard_control.suppress_deck` | hazard_control.js:814 | game_loop.py:2589 |
| `hazard_control.vent_room` | hazard_control.js:789 | game_loop.py:2592 |
| `hazard_control.cancel_vent` | hazard_control.js:786 | game_loop.py:2595 |
| `hazard_control.dispatch_fire_team` | hazard_control.js:753 | game_loop.py:2598 |
| `hazard_control.cancel_fire_team` | hazard_control.js:750 | game_loop.py:2601 |
| `hazard_control.force_field` | hazard_control.js:761 | game_loop.py:2605 |
| `hazard_control.seal_bulkhead` | hazard_control.js:765 | game_loop.py:2608 |
| `hazard_control.unseal_bulkhead` | hazard_control.js:768 | game_loop.py:2611 |
| `hazard_control.order_evacuation` | hazard_control.js:817 | game_loop.py:2614 |
| `hazard_control.cycle_vent` | hazard_control.js:844 | game_loop.py:2617 |
| `hazard_control.set_vent` | hazard_control.js:847 | game_loop.py:2620 |
| `hazard_control.emergency_vent_space` | hazard_control.js:798 | game_loop.py:2623 |
| `hazard_control.cancel_space_vent` | hazard_control.js:795 | game_loop.py:2633 |
| `hazard_control.dispatch_decon_team` | hazard_control.js:779 | game_loop.py:2637 |
| `hazard_control.cancel_decon_team` | hazard_control.js:776 | game_loop.py:2640 |
| `hazard_control.reinforce_section` | hazard_control.js:808 | game_loop.py:2644 |
| `hazard_control.cancel_reinforcement` | hazard_control.js:805 | game_loop.py:2647 |
| `hazard_control.seal_connection` | hazard_control.js:839 | game_loop.py:2651 |
| `hazard_control.unseal_connection` | hazard_control.js:836 | game_loop.py:2654 |
| `hazard_control.override_security_lock` | hazard_control.js | game_loop.py:2657 |
| `hazard_control.redirect_battery` | hazard_control.js | game_loop.py:2660 |
| `hazard_control.set_evacuation_order` | hazard_control.js | game_loop.py:2663 |
| `hazard_control.launch_pod` | hazard_control.js | game_loop.py:2666 |

---

### QUARTERMASTER

#### EMITS (server broadcasts received by quartermaster client)

| Signal Key | Source File | Target Roles |
|---|---|---|
| `ship.state` | game_loop.py:1747 | ALL |
| `ship.alert_changed` | captain.py:119 | ALL |
| `ship.hull_hit` | game_loop.py:2057 | ALL |
| `vendor.*` | game_loop.py:1829 | captain, comms, quartermaster |
| `negotiation.*` | game_loop.py:1837 | captain, comms, quartermaster |
| `salvage.*` | game_loop.py:1845 | captain, engineering, quartermaster |
| `rationing.*` | game_loop.py:1853 | captain, engineering, quartermaster |
| `game.started` | main.py:779 | ALL |
| `game.over` | game_loop.py:1351 | ALL |

#### EXPECTS (messages quartermaster client sends to server)

| Signal Key | Client File:Line | Handler |
|---|---|---|
| `rationing.set_level` | quartermaster.js:94 | queue forward → glrat |
| `negotiation.open_channel` | quartermaster.js | queue forward → glng |
| `negotiation.close_channel` | quartermaster.js | queue forward → glng |
| `negotiation.start` | quartermaster.js | queue forward → glng |
| `negotiation.accept` | quartermaster.js | queue forward → glng |
| `negotiation.counter` | quartermaster.js | queue forward → glng |
| `negotiation.walk_away` | quartermaster.js | queue forward → glng |
| `negotiation.bluff` | quartermaster.js | queue forward → glng |
| `negotiation.barter` | quartermaster.js | queue forward → glng |
| `salvage.assess` | quartermaster.js | queue forward → glsalv |
| `salvage.begin` | quartermaster.js | queue forward → glsalv |
| `salvage.cancel` | quartermaster.js | queue forward → glsalv |

---

## 2. Connectivity Matrix

Rows = sender station, Columns = receiver station. Shows whether the sender emits signals that the receiver's client handles.

Legend: **S** = sends signals to, **R** = receives shared state, **F** = function-call coupling, **-** = self, **.** = no direct path

| | CAP | HLM | WPN | ENG | SCI | MED | SEC | COM | EW | FLO | OPS | HC | QM |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **CAP** | - | S | S | S | S | S | S | S | S | S | S | S | S |
| **HLM** | . | - | . | . | . | . | . | . | . | . | . | . | . |
| **WPN** | S | S | - | . | S | S | . | . | . | . | . | S | . |
| **ENG** | . | . | . | - | . | . | . | . | . | . | . | S | . |
| **SCI** | S | S | . | . | - | . | . | . | . | . | . | . | . |
| **MED** | . | . | . | . | . | - | . | . | . | . | . | . | . |
| **SEC** | S | . | . | . | . | S | - | . | . | . | . | S | . |
| **COM** | S | S | S | . | S | . | S | - | . | . | . | . | . |
| **EW** | . | . | . | . | . | . | . | . | - | . | . | . | . |
| **FLO** | S | . | S | . | S | S | . | . | S | - | . | . | . |
| **OPS** | S | S | S | . | S | . | . | . | S | S | - | . | . |
| **HC** | . | . | . | S | . | S | . | . | . | . | . | - | . |
| **QM** | S | . | . | S | . | . | . | S | . | . | . | . | - |

### Key Cross-Station Signal Flows

- **Captain → ALL**: `ship.alert_changed`, `captain.override_changed`, `crew.reassignment_started` (broadcast to all)
- **Weapons → Medical**: `weapons.nuclear_warning`
- **Weapons → HC**: `weapons.nuclear_radiation`
- **Weapons → Science**: `weapons.ion_effect`
- **Security → Medical**: `security.squad_casualty`, `security.casualty_prediction`
- **Security → HC**: `security.boarding_prestage_warning`
- **Security → Captain**: `security.boarding_alert`, `security.party_eliminated`
- **Comms → Captain/Helm/Science/Weapons**: `comms.contacts`, `comms.contact_merged`
- **Comms → Security**: `comms.boarding_intercept`
- **Comms → dynamic**: `comms.intel_routed` (target station varies)
- **Operations → Helm/Captain/Weapons**: `operations.overlay`
- **Operations → Captain**: `operations.intel_analysis`
- **Operations → dynamic roles**: `operations.event` (varies per event type)
- **HC → Medical**: `hazcon.injury_predictions`, `hazcon.evacuation_warning`
- **HC → Engineering**: `hazcon.breach_repaired`, shared `engineering.dc_state`
- **Flight Ops → Medical**: `flight_ops.rescue_eta`
- **Flight Ops → Science/Weapons/EW**: cross-station drone events
- **QM (vendor/salvage/rationing)**: events → captain + comms/engineering + quartermaster

---

## 3. Dead Signal Report

Signals the server broadcasts that have **NO client-side handler** in any JS file.

| # | Signal Key | Server Source | Target Roles | Severity |
|---|---|---|---|---|
| 1 | `science.sensor_anomaly` | game_loop.py:1659 | science | **HIGH** — sandbox event wasted |
| 2 | `medical_ship.state` | game_loop.py:1999 | medical | **HIGH** — medical ship data never displayed |
| 3 | `ship.reactor_shutdown` | game_loop.py:956 | ALL | **HIGH** — critical event invisible to players |
| 4 | `ship.resupplied` | game_loop_mission.py:256 | ALL | **MED** — resupply confirmation lost |
| 5 | `resources.critical` | game_loop.py:2040 | ALL | **HIGH** — critical resource alert invisible |
| 6 | `resources.warning` | game_loop.py:2044 | captain | **MED** — resource warning invisible to captain |
| 7 | `crew.factor_changed` | game_loop.py:2022 | dynamic | **LOW** — efficiency change; data in ship.state |
| 8 | `crew.reassignment_complete` | game_loop.py:2051 | ALL | **MED** — reassignment completion unconfirmed |
| 9 | `hazard.status` | game_loop.py:2062 | ALL | **MED** — environmental hazard overlay missing |
| 10 | `ship.mining_event` | game_loop.py:1164 | engineering | **LOW** — mining feedback missing |
| 11 | `carrier.state` | game_loop.py:2126 | flight_ops | **HIGH** — carrier-specific UI data missing |
| 12 | `flag_bridge.state` | game_loop.py:2210 | captain, ops | **HIGH** — cruiser flag bridge invisible |
| 13 | `flag_bridge.drawings` | game_loop.py:2214 | helm, ops | **HIGH** — tactical drawings invisible |
| 14 | `flag_bridge.priority` | game_loop.py:2218 | weapons | **HIGH** — flag bridge priority target lost |
| 15 | `spinal.state` | game_loop.py:2228 | weapons, captain | **HIGH** — battleship spinal mount invisible |
| 16 | `station.reinforcement_call` | game_loop.py:1226 | ALL | **MED** — enemy station reinforcement unnoticed |
| 17 | `station.component_destroyed` | game_loop.py:1231 | ALL | **MED** — station component kill unconfirmed |
| 18 | `station.destroyed` | game_loop.py:1248 | ALL | **MED** — station destruction event missing |
| 19 | `station.captured` | game_loop.py:1257 | ALL | **MED** — station capture unnoticed |
| 20 | `station.hull_hit` | game_loop_weapons.py:1232 | ALL | **LOW** — hit feedback on enemy stations |
| 21 | `security.boarding_alert` | game_loop.py:2429 | security, captain | **HIGH** — see Key Mismatch #1 |

**Total: 21 dead signals** (8 HIGH, 8 MED, 5 LOW)

---

## 4. Orphan Handler Report

Client handlers that listen for signal types the server **never sends**.

| # | Signal Key | Client File:Line | Expected Source | Severity |
|---|---|---|---|---|
| 1 | `security.boarding_started` | security.js:923 | security events | **HIGH** — see Key Mismatch #1 |
| 2 | `crew.roster_update` | shared/crew_roster.js:119 | crew system | **MED** — handler registered but never triggered |

**Total: 2 orphan handlers**

---

## 5. Key Mismatch Report

Signal keys where the server sends one key but the client listens for a different key.

### Mismatch #1: Security Boarding Sound (HIGH)

| | Key | Location |
|---|---|---|
| **Server sends** | `security.boarding_alert` | game_loop.py:2429 |
| **Client expects** | `security.boarding_started` | security.js:923 |
| **Effect** | Boarding alert sound (`SoundBank.play('boarding_alert')`) **never plays** |
| **Fix** | Change client to `on('security.boarding_alert', ...)` OR change server to emit `security.boarding_started` |

### Mismatch #2: Security Lockdown All (MED)

| | Key | Location |
|---|---|---|
| **Client sends** | `security.lockdown_all` | security.js:735 |
| **Server handles** | `security.lockdown_deck` only | game_loop.py:2922 |
| **Effect** | "Lockdown All" button sends a message the server silently drops |
| **Fix** | Add `security.lockdown_all` handler in game_loop.py that calls `gls.lockdown_all()` |

**Total: 2 key mismatches**

---

## 6. Shared State Audit

Cross-station coupling via direct function calls (not messages). These represent implicit signal paths where one station's module reads/writes another's state.

### Operations (glops) — read by many

| Reader | Function Called | Purpose |
|---|---|---|
| Weapons | `glops.get_vulnerable_facing()` | +25% beam damage vs facing |
| Weapons | `glops.get_weapons_helm_sync_bonus()` | +15% accuracy, +10% damage |
| Weapons | `glops.get_priority_subsystem()` | subsystem targeting |
| Sensors | `glops.get_sensor_focus_bonus()` | +25% scan range in focus zone |
| EW | `glops.get_sensor_focus_bonus()` | +20% jam effectiveness |
| Comms | `glops.get_sensor_focus_bonus()` | +15% decode speed |
| Helm | `glops.get_evasion_alert_active()` | evasion maneuver indicator |
| HC | `glops.get_damage_priority_list()` | repair prioritization |
| All stations | `glops.add_feed_event()` | push events to Ops feed |

### Captain Orders (glcord) — read by many

| Reader | Function Called | Purpose |
|---|---|---|
| Weapons | `glcord.get_priority_target()` | gold diamond targeting |
| EW | `glcord.get_active_order()` | silent running affects ECM |
| Drone AI | `glcord.get_priority_target()` | auto-engage priority |
| Helm | `glcord.is_all_stop_active()` | throttle lock |
| All systems | `glcord.get_active_order()` | order-specific modifiers |

### EW (glew) — read by many

| Reader | Function Called | Purpose |
|---|---|---|
| Sensors | `glew.get_stealth_sensor_modifier()` | stealth affects detection |
| Sensors | `glew.get_ghost_contacts()` | ghost contacts in sensor list |
| Sensors | `glew.get_freq_locked_ids()` | frequency-locked enemy IDs |
| Weapons | `glew.is_stealth_engaged()` | fire breaks stealth |
| Science | `glew.is_stealth_engaged()` | scan breaks stealth |
| Comms | `glew.is_stealth_engaged()` | transmit breaks stealth |
| Game loop | `glew.record_weapons_fire()` | emission tracking |

### Security (gls) — read by many

| Reader | Function Called | Purpose |
|---|---|---|
| All systems | `gls.is_boarding_active()` | crew_factor penalty |
| HC | `gls.apply_vent_damage_to_boarders()` | vent affects boarders |
| HC | `gls.apply_fire_damage_to_marines()` | fire affects marines |
| Sensors | boarding → crew_factor → system efficiency | indirect detection degradation |

### Engineering (gle) — read by many

| Reader | Function Called | Purpose |
|---|---|---|
| HC | `gle.get_teams_on_deck()` | repair team locations |
| HC | fire suppression power gate | engineering power enables suppression |
| Atmosphere | engineering power → life support efficiency | LS depends on power |

### Rationing (glrat) — read by many

| Reader | Function Called | Purpose |
|---|---|---|
| All consuming systems | `glrat.get_consumption_multiplier()` | resource usage rate |
| Medical | consumption affects supplies | treatment limited by rationing |
| Flight Ops | consumption affects drone fuel | sortie rate limited |
| DC/Engineering | consumption affects repair parts | repair speed limited |

### Flight Ops (glfo) — read by some

| Reader | Function Called | Purpose |
|---|---|---|
| EW | `glfo.get_ecm_drone_effectiveness()` | ECM drone jam bonus |
| Sensors | `glfo.get_detection_bubbles()` | drone detection range bubbles |
| Engineering | `glfo.get_flight_deck_power_draw()` | power budget calculation |

### Hazard Control (glhc) — read by some

| Reader | Function Called | Purpose |
|---|---|---|
| Security | `glhc.get_smoke_rooms()` | smoke halves detection |
| Weapons | structural collapse → room offline | system availability |
| All | atmosphere penalties → crew efficiency | contamination/temp effects |

---

## 7. Client-Side Signal Check

### Signals handled by shared client utilities (not station-specific)

| Signal Key | Client Handler | File |
|---|---|---|
| `puzzle.started` | puzzle_renderer.js:40 | Shared puzzle overlay |
| `puzzle.result` | puzzle_renderer.js:41 | Shared puzzle overlay |
| `puzzle.assist_applied` | puzzle_renderer.js:42 | Shared puzzle overlay |
| `crew.notification` | shared/notifications.js:79 | Floating notification |
| `crew.roster` | shared/crew_roster.js:118 | Crew manifest panel |
| `game.all_ready` | briefing.js:125 | Pre-game briefing |
| `lobby.error` | lobby.js:115 | Lobby error display |
| `lobby.janitor_available` | lobby.js:117 | Easter egg |
| `janitor.state` | janitor.js:80 | Secret station |
| `janitor.task_result` | janitor.js:81 | Secret station |
| `training.hint` | training_hud.js | Training mode overlay |

### Client coverage summary

| Station | Server Emits | Client Handles | Coverage |
|---|---|---|---|
| Captain | 33 | 33 | 100% |
| Helm | 14 | 14 | 100% |
| Weapons | 17 | 17 | 100% |
| Engineering | 12 | 12 | 100% |
| Science | 13 | 13 | 100% |
| Medical | 8 | 8 | 100% |
| Security | 6 | 5 | **83%** (missing: `security.boarding_alert`) |
| Comms | 14 | 14 | 100% |
| EW | 6 | 6 | 100% |
| Flight Ops | 8 | 8 | 100% |
| Operations | 7 | 7 | 100% |
| Hazard Control | 7 | 7 | 100% |
| Quartermaster | 9 | 9 | 100% |

### Cross-station broadcasts with no client handler (full list in Section 3)

21 signals broadcast by server with no client handler anywhere. Most notable:
- Ship-class features (`carrier.state`, `flag_bridge.*`, `spinal.state`) — entire UI systems not wired
- Critical alerts (`ship.reactor_shutdown`, `resources.critical`) — emergency events invisible
- Enemy station events (`station.destroyed`, `station.captured`) — feedback missing

---

## 8. Summary Statistics

| Metric | Count |
|---|---|
| **Total unique server broadcast types** | 99 |
| **Total client-handled signal types** | 99 |
| **Total client-sent message types** | 89 |
| **Global broadcasts (ALL clients)** | ~35 types |
| **Role-filtered broadcasts** | ~50 types |
| **Dead signals (server sends, no handler)** | **0** |
| **Orphan handlers (client listens, nothing sends)** | **0** |
| **Key mismatches** | **0** |
| **Shared state couplings (function-call)** | 40+ |
| **Stations with 100% client coverage** | 13 / 13 |
| **Cross-station message flows** | 20+ direct paths |

### Fix History (v0.08-signals)

All 25 issues identified in the original audit have been resolved across 4 commits:

| Commit | Tier | Fixes | Summary |
|---|---|---|---|
| `242d291` | v0.08-signals.1 | 2 | Key mismatches: `security.boarding_alert` + `security.lockdown_all` |
| `014847a` | v0.08-signals.2 | 7 | HIGH dead signals: reactor_shutdown, resources.critical, carrier/flag_bridge/spinal state |
| `7212abd` | v0.08-signals.3 | 8 | MED dead signals: resupplied, reassignment, hazard, station combat, resources.warning |
| `5aaa3a9` | v0.08-signals.4 | 8 | LOW dead signals + orphans: crew.factor, mining, hull_hit, medical_ship, anomaly, roster_update |

**Verification:** 6609 tests passing after each commit. Re-audit confirmed 0 dead signals, 0 orphan handlers, 0 key mismatches.

---

*End of Signal Audit Report*
