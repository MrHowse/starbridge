"""
Game Save/Resume System — v0.04f.

Provides save_game(), list_saves(), load_save(), and restore_game().
Saves are written to saves/{id}.json in the project root.

Save format:
  {
    "save_id": "20260221_143022_first_contact",
    "saved_at": "2026-02-21T14:30:22",
    "mission_id": "first_contact",
    "difficulty_preset": "officer",
    "ship_class": "frigate",
    "tick_count": 1234,
    "ship": { ... },
    "entities": { enemies, torpedoes, stations, asteroids, hazards },
    "modules": { weapons, medical, security, flight_ops, damage_control,
                 comms, captain_log, training, ew, tactical, mission, game_state },
  }
"""
from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

import server.game_loop_weapons as glw
import server.game_loop_medical_v2 as glmed
import server.game_loop_security as gls
import server.game_loop_flight_ops as glfo
import server.game_loop_damage_control as gldc
import server.game_loop_comms as glco
import server.game_loop_captain as glcap
import server.game_loop_training as gltr
import server.game_loop_ew as glew
import server.game_loop_tactical as gltac
import server.game_loop_mission as glm
import server.game_loop_docking as gldo
import server.game_loop_engineering as gle
import server.game_loop_dynamic_missions as gldm
import server.game_loop_janitor as glj
import server.game_loop_mining as glmn
import server.game_loop_flag_bridge as glfb
import server.game_loop_spinal_mount as glsm
import server.game_loop_carrier_ops as glcar
import server.game_loop_medical_ship as glms
import server.equipment_modules as gleq
import server.loadout as gllo

from server.difficulty import DifficultySettings
from server.models.crew import CrewRoster, DeckCrew
from server.models.interior import ShipInterior, make_default_interior
from server.models.security import Intruder, MarineSquad
from server.models.ship import Ship, ShipSystem, Shields
from server.models.world import Asteroid, Enemy, Hazard, Station, Torpedo, World

logger = logging.getLogger("starbridge.save_system")

SAVES_DIR = Path(__file__).parent.parent / "saves"


# ---------------------------------------------------------------------------
# Ship serialisation helpers
# ---------------------------------------------------------------------------


def _serialise_ship(ship: Ship) -> dict:
    """Convert Ship to a JSON-serialisable dict."""
    return {
        "name": ship.name,
        "x": ship.x, "y": ship.y,
        "heading": ship.heading,
        "target_heading": ship.target_heading,
        "velocity": ship.velocity,
        "throttle": ship.throttle,
        "hull": ship.hull,
        "hull_max": ship.hull_max,
        "max_speed_base": ship.max_speed_base,
        "acceleration_base": ship.acceleration_base,
        "turn_rate_base": ship.turn_rate_base,
        "target_profile": ship.target_profile,
        "armour": ship.armour,
        "armour_max": ship.armour_max,
        "armour_zones": dict(ship.armour_zones) if ship.armour_zones else None,
        "armour_zones_max": dict(ship.armour_zones_max) if ship.armour_zones_max else None,
        "beam_damage_base": ship.beam_damage_base,
        "beam_fire_rate": ship.beam_fire_rate,
        "beam_arc_deg": ship.beam_arc_deg,
        "beam_count": ship.beam_count,
        "torpedo_tube_count": ship.torpedo_tube_count,
        "pd_turret_count": ship.pd_turret_count,
        "fuel_multiplier": ship.fuel_multiplier,
        "sensor_range_base": ship.sensor_range_base,
        "shield_capacity": ship.shield_capacity,
        "shield_recharge_rate": ship.shield_recharge_rate,
        "docked_at": ship.docked_at,
        "shields": {
            "fore": ship.shields.fore, "aft": ship.shields.aft,
            "port": ship.shields.port, "starboard": ship.shields.starboard,
        },
        "shield_focus":        ship.shield_focus,
        "shield_distribution": ship.shield_distribution,
        "systems": {
            name: {
                "power": sys.power,
                "health": sys.health,
                "_captain_offline": sys._captain_offline,
            }
            for name, sys in ship.systems.items()
        },
        "repair_focus": ship.repair_focus,
        "alert_level": ship.alert_level,
        "medical_supplies": ship.medical_supplies,
        "cargo_capacity": ship.cargo_capacity,
        "cargo": dict(ship.cargo),
        "countermeasure_charges": ship.countermeasure_charges,
        "ew_countermeasure_active": ship.ew_countermeasure_active,
        "crew": _serialise_crew(ship.crew),
        "interior": _serialise_interior(ship.interior),
        "difficulty": {
            "enemy_damage_multiplier": ship.difficulty.enemy_damage_multiplier,
            "enemy_accuracy": ship.difficulty.enemy_accuracy,
            "enemy_health_multiplier": ship.difficulty.enemy_health_multiplier,
            "enemy_count_multiplier": ship.difficulty.enemy_count_multiplier,
            "enemy_ai_aggression": ship.difficulty.enemy_ai_aggression,
            "component_damage_chance": ship.difficulty.component_damage_chance,
            "component_severity_multiplier": ship.difficulty.component_severity_multiplier,
            "cook_off_chance_multiplier": ship.difficulty.cook_off_chance_multiplier,
            "repair_speed_multiplier": ship.difficulty.repair_speed_multiplier,
            "injury_chance": ship.difficulty.injury_chance,
            "injury_severity_bias": ship.difficulty.injury_severity_bias,
            "degradation_timer_multiplier": ship.difficulty.degradation_timer_multiplier,
            "death_timer_multiplier": ship.difficulty.death_timer_multiplier,
            "contagion_spread_chance": ship.difficulty.contagion_spread_chance,
            "starting_torpedo_multiplier": ship.difficulty.starting_torpedo_multiplier,
            "medical_supply_multiplier": ship.difficulty.medical_supply_multiplier,
            "battery_capacity_multiplier": ship.difficulty.battery_capacity_multiplier,
            "fuel_consumption_multiplier": ship.difficulty.fuel_consumption_multiplier,
            "sensor_range_multiplier": ship.difficulty.sensor_range_multiplier,
            "scan_time_multiplier": ship.difficulty.scan_time_multiplier,
            "fog_of_war_reveal": ship.difficulty.fog_of_war_reveal,
            "hazard_damage_multiplier": ship.difficulty.hazard_damage_multiplier,
            "event_interval_multiplier": ship.difficulty.event_interval_multiplier,
            "event_overlap_max": ship.difficulty.event_overlap_max,
            "docking_service_multiplier": ship.difficulty.docking_service_multiplier,
            "boarding_frequency_multiplier": ship.difficulty.boarding_frequency_multiplier,
            "puzzle_time_mult": ship.difficulty.puzzle_time_mult,
            "hints_enabled": ship.difficulty.hints_enabled,
        },
    }


def _serialise_crew(crew: CrewRoster) -> dict:
    return {
        "decks": {
            name: {
                "deck_name": deck.deck_name,
                "total": deck.total,
                "active": deck.active,
                "injured": deck.injured,
                "critical": deck.critical,
                "dead": deck.dead,
            }
            for name, deck in crew.decks.items()
        }
    }


def _serialise_interior(interior: ShipInterior) -> dict:
    return {
        "room_states": {
            rid: {"state": room.state, "door_sealed": room.door_sealed}
            for rid, room in interior.rooms.items()
        },
        "marine_squads": [
            {
                "id": sq.id, "room_id": sq.room_id,
                "health": sq.health, "action_points": sq.action_points, "count": sq.count,
            }
            for sq in interior.marine_squads
        ],
        "intruders": [
            {
                "id": intr.id, "room_id": intr.room_id,
                "objective_id": intr.objective_id,
                "health": intr.health, "move_timer": intr.move_timer,
            }
            for intr in interior.intruders
        ],
    }


def _serialise_entities(world: World) -> dict:
    return {
        "enemies": [
            {
                "id": e.id, "type": e.type, "x": e.x, "y": e.y,
                "heading": e.heading, "velocity": e.velocity,
                "hull": e.hull, "shield_front": e.shield_front, "shield_rear": e.shield_rear,
                "ai_state": e.ai_state, "beam_cooldown": e.beam_cooldown,
                "scan_state": e.scan_state, "stun_ticks": e.stun_ticks,
                "jam_factor": e.jam_factor, "intrusion_stun_ticks": e.intrusion_stun_ticks,
                "shield_frequency": e.shield_frequency,
            }
            for e in world.enemies
        ],
        "torpedoes": [
            {
                "id": t.id, "owner": t.owner, "x": t.x, "y": t.y,
                "heading": t.heading, "velocity": t.velocity,
                "distance_travelled": t.distance_travelled,
                "torpedo_type": t.torpedo_type,
            }
            for t in world.torpedoes
        ],
        "stations": [
            {
                "id": s.id, "x": s.x, "y": s.y,
                "name": s.name,
                "station_type": s.station_type,
                "faction": s.faction,
                "services": s.services,
                "docking_range": s.docking_range,
                "docking_ports": s.docking_ports,
                "transponder_active": s.transponder_active,
                "shields": s.shields, "shields_max": s.shields_max,
                "hull": s.hull, "hull_max": s.hull_max,
                "inventory": s.inventory,
                "requires_scan": s.requires_scan,
            }
            for s in world.stations
        ],
        "asteroids": [
            {"id": a.id, "x": a.x, "y": a.y, "radius": a.radius}
            for a in world.asteroids
        ],
        "hazards": [
            {
                "id": h.id, "x": h.x, "y": h.y, "radius": h.radius,
                "hazard_type": h.hazard_type, "label": h.label,
            }
            for h in world.hazards
        ],
    }


# ---------------------------------------------------------------------------
# Ship deserialisation helpers
# ---------------------------------------------------------------------------


def _deserialise_ship(data: dict, ship: Ship) -> None:
    """Restore Ship state from save data in-place."""
    ship.name = data.get("name", ship.name)
    ship.x = float(data.get("x", ship.x))
    ship.y = float(data.get("y", ship.y))
    ship.heading = float(data.get("heading", ship.heading))
    ship.target_heading = float(data.get("target_heading", ship.target_heading))
    ship.velocity = float(data.get("velocity", ship.velocity))
    ship.throttle = float(data.get("throttle", ship.throttle))
    ship.hull = float(data.get("hull", ship.hull))
    ship.hull_max = float(data.get("hull_max", ship.hull))
    ship.max_speed_base = float(data.get("max_speed_base", ship.max_speed_base))
    ship.acceleration_base = float(data.get("acceleration_base", ship.acceleration_base))
    ship.turn_rate_base = float(data.get("turn_rate_base", ship.turn_rate_base))
    ship.target_profile = float(data.get("target_profile", ship.target_profile))
    ship.armour = float(data.get("armour", ship.armour))
    ship.armour_max = float(data.get("armour_max", ship.armour_max))
    ship.armour_zones = data.get("armour_zones")
    ship.armour_zones_max = data.get("armour_zones_max")
    ship.beam_damage_base = float(data.get("beam_damage_base", ship.beam_damage_base))
    ship.beam_fire_rate = float(data.get("beam_fire_rate", ship.beam_fire_rate))
    ship.beam_arc_deg = float(data.get("beam_arc_deg", ship.beam_arc_deg))
    ship.beam_count = int(data.get("beam_count", ship.beam_count))
    ship.torpedo_tube_count = int(data.get("torpedo_tube_count", ship.torpedo_tube_count))
    ship.pd_turret_count = int(data.get("pd_turret_count", ship.pd_turret_count))
    ship.fuel_multiplier = float(data.get("fuel_multiplier", ship.fuel_multiplier))
    ship.sensor_range_base = float(data.get("sensor_range_base", ship.sensor_range_base))
    ship.shield_capacity = float(data.get("shield_capacity", ship.shield_capacity))
    ship.shield_recharge_rate = float(data.get("shield_recharge_rate", ship.shield_recharge_rate))
    ship.docked_at = data.get("docked_at")

    shields_d = data.get("shields", {})
    ship.shields.fore      = float(shields_d.get("fore",      ship.shields.fore))
    ship.shields.aft       = float(shields_d.get("aft",       ship.shields.aft))
    ship.shields.port      = float(shields_d.get("port",      ship.shields.port))
    ship.shields.starboard = float(shields_d.get("starboard", ship.shields.starboard))
    ship.shield_focus        = data.get("shield_focus",        ship.shield_focus)
    ship.shield_distribution = data.get("shield_distribution", ship.shield_distribution)

    for sys_name, sys_d in data.get("systems", {}).items():
        sys_obj = ship.systems.get(sys_name)
        if sys_obj is None:
            # Add unknown system (ship class may differ from save).
            sys_obj = ShipSystem(sys_name)
            ship.systems[sys_name] = sys_obj
        sys_obj.power = float(sys_d.get("power", sys_obj.power))
        sys_obj.health = float(sys_d.get("health", sys_obj.health))
        sys_obj._captain_offline = bool(sys_d.get("_captain_offline", False))

    ship.repair_focus = data.get("repair_focus")
    ship.alert_level = data.get("alert_level", "green")
    ship.medical_supplies = int(data.get("medical_supplies", ship.medical_supplies))
    ship.cargo_capacity = float(data.get("cargo_capacity", ship.cargo_capacity))
    ship.cargo = dict(data.get("cargo", ship.cargo))
    ship.countermeasure_charges = int(data.get("countermeasure_charges", ship.countermeasure_charges))
    ship.ew_countermeasure_active = bool(data.get("ew_countermeasure_active", False))

    crew_d = data.get("crew", {})
    if crew_d:
        _deserialise_crew(crew_d, ship.crew)

    interior_d = data.get("interior", {})
    if interior_d:
        _deserialise_interior(interior_d, ship.interior)

    diff_d = data.get("difficulty", {})
    if diff_d:
        # Backward compat: old saves used "enemy_damage_mult" etc.
        ship.difficulty = DifficultySettings(
            enemy_damage_multiplier=float(diff_d.get(
                "enemy_damage_multiplier", diff_d.get("enemy_damage_mult", 1.0))),
            enemy_accuracy=float(diff_d.get("enemy_accuracy", 1.0)),
            enemy_health_multiplier=float(diff_d.get("enemy_health_multiplier", 1.0)),
            enemy_count_multiplier=float(diff_d.get("enemy_count_multiplier", 1.0)),
            enemy_ai_aggression=float(diff_d.get("enemy_ai_aggression", 0.75)),
            component_damage_chance=float(diff_d.get("component_damage_chance", 0.5)),
            component_severity_multiplier=float(diff_d.get("component_severity_multiplier", 1.0)),
            cook_off_chance_multiplier=float(diff_d.get("cook_off_chance_multiplier", 1.0)),
            repair_speed_multiplier=float(diff_d.get("repair_speed_multiplier", 1.0)),
            injury_chance=float(diff_d.get("injury_chance", 0.4)),
            injury_severity_bias=float(diff_d.get("injury_severity_bias", 0.5)),
            degradation_timer_multiplier=float(diff_d.get("degradation_timer_multiplier", 1.0)),
            death_timer_multiplier=float(diff_d.get("death_timer_multiplier", 1.0)),
            contagion_spread_chance=float(diff_d.get("contagion_spread_chance", 0.3)),
            starting_torpedo_multiplier=float(diff_d.get("starting_torpedo_multiplier", 1.0)),
            medical_supply_multiplier=float(diff_d.get("medical_supply_multiplier", 1.0)),
            battery_capacity_multiplier=float(diff_d.get("battery_capacity_multiplier", 1.0)),
            fuel_consumption_multiplier=float(diff_d.get("fuel_consumption_multiplier", 1.0)),
            sensor_range_multiplier=float(diff_d.get("sensor_range_multiplier", 1.0)),
            scan_time_multiplier=float(diff_d.get("scan_time_multiplier", 1.0)),
            fog_of_war_reveal=float(diff_d.get("fog_of_war_reveal", 0.2)),
            hazard_damage_multiplier=float(diff_d.get("hazard_damage_multiplier", 1.0)),
            event_interval_multiplier=float(diff_d.get("event_interval_multiplier", 1.0)),
            event_overlap_max=int(diff_d.get("event_overlap_max", 2)),
            docking_service_multiplier=float(diff_d.get("docking_service_multiplier", 1.0)),
            boarding_frequency_multiplier=float(diff_d.get("boarding_frequency_multiplier", 1.0)),
            puzzle_time_mult=float(diff_d.get("puzzle_time_mult", 1.0)),
            hints_enabled=bool(diff_d.get("hints_enabled", False)),
        )


def _deserialise_crew(data: dict, crew: CrewRoster) -> None:
    for deck_name, deck_d in data.get("decks", {}).items():
        deck = crew.decks.get(deck_name)
        if deck is None:
            deck = DeckCrew(deck_name=deck_name, total=0, active=0)
            crew.decks[deck_name] = deck
        deck.total = int(deck_d.get("total", deck.total))
        deck.active = int(deck_d.get("active", deck.active))
        deck.injured = int(deck_d.get("injured", deck.injured))
        deck.critical = int(deck_d.get("critical", getattr(deck, "critical", 0)))
        deck.dead = int(deck_d.get("dead", deck.dead))


def _deserialise_interior(data: dict, interior: ShipInterior) -> None:
    for rid, room_d in data.get("room_states", {}).items():
        room = interior.rooms.get(rid)
        if room is not None:
            room.state = room_d.get("state", "normal")
            room.door_sealed = bool(room_d.get("door_sealed", False))

    interior.marine_squads.clear()
    for sq_d in data.get("marine_squads", []):
        sq = MarineSquad(
            id=sq_d["id"],
            room_id=sq_d["room_id"],
            health=float(sq_d.get("health", 100.0)),
            action_points=float(sq_d.get("action_points", 10.0)),
            count=int(sq_d.get("count", 4)),
        )
        interior.marine_squads.append(sq)

    interior.intruders.clear()
    for intr_d in data.get("intruders", []):
        intr = Intruder(
            id=intr_d["id"],
            room_id=intr_d["room_id"],
            objective_id=intr_d.get("objective_id", ""),
            health=float(intr_d.get("health", 100.0)),
        )
        intr.move_timer = float(intr_d.get("move_timer", 0.0))
        interior.intruders.append(intr)


def _deserialise_entities(data: dict, world: World) -> None:
    world.enemies.clear()
    for e in data.get("enemies", []):
        enemy = Enemy(
            id=e["id"], type=e["type"],
            x=float(e["x"]), y=float(e["y"]),
            heading=float(e.get("heading", 0.0)),
            velocity=float(e.get("velocity", 0.0)),
            hull=float(e.get("hull", 100.0)),
            shield_front=float(e.get("shield_front", 100.0)),
            shield_rear=float(e.get("shield_rear", 100.0)),
            ai_state=e.get("ai_state", "idle"),
            beam_cooldown=float(e.get("beam_cooldown", 0.0)),
            scan_state=e.get("scan_state", "unknown"),
            stun_ticks=int(e.get("stun_ticks", 0)),
            jam_factor=float(e.get("jam_factor", 0.0)),
            intrusion_stun_ticks=int(e.get("intrusion_stun_ticks", 0)),
            shield_frequency=e.get("shield_frequency", ""),
        )
        world.enemies.append(enemy)

    world.torpedoes.clear()
    for t in data.get("torpedoes", []):
        torp = Torpedo(
            id=t["id"], owner=t["owner"],
            x=float(t["x"]), y=float(t["y"]),
            heading=float(t["heading"]),
            velocity=float(t.get("velocity", 500.0)),
            distance_travelled=float(t.get("distance_travelled", 0.0)),
            torpedo_type=t.get("torpedo_type", "standard"),
        )
        world.torpedoes.append(torp)

    world.stations.clear()
    for s in data.get("stations", []):
        st = Station(
            id=s["id"], x=float(s["x"]), y=float(s["y"]),
            name=s.get("name", ""),
            station_type=s.get("station_type", "military"),
            faction=s.get("faction", "friendly"),
            services=list(s.get("services", [])),
            docking_range=float(s.get("docking_range", 2_000.0)),
            docking_ports=int(s.get("docking_ports", 2)),
            transponder_active=bool(s.get("transponder_active", True)),
            shields=float(s.get("shields", 0.0)),
            shields_max=float(s.get("shields_max", 0.0)),
            hull=float(s.get("hull", 500.0)),
            hull_max=float(s.get("hull_max", 500.0)),
            inventory=dict(s.get("inventory", {})),
            requires_scan=bool(s.get("requires_scan", False)),
        )
        world.stations.append(st)

    world.asteroids.clear()
    for a in data.get("asteroids", []):
        world.asteroids.append(
            Asteroid(id=a["id"], x=float(a["x"]), y=float(a["y"]),
                     radius=float(a.get("radius", 1000.0)))
        )

    world.hazards.clear()
    for h in data.get("hazards", []):
        world.hazards.append(
            Hazard(
                id=h["id"], x=float(h["x"]), y=float(h["y"]),
                radius=float(h.get("radius", 10000.0)),
                hazard_type=h.get("hazard_type", "nebula"),
                label=h.get("label"),
            )
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_game(
    world: World,
    mission_id: str,
    difficulty_preset: str,
    ship_class: str,
    tick_count: int,
    game_state: dict | None = None,
) -> str:
    """Serialise all game state to a JSON file. Returns the save_id."""
    now = datetime.datetime.now()
    safe_mission = mission_id.replace("/", "_").replace(".", "_")
    save_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{safe_mission}"

    save_data = {
        "save_id": save_id,
        "saved_at": now.isoformat(timespec="seconds"),
        "mission_id": mission_id,
        "difficulty_preset": difficulty_preset,
        "ship_class": ship_class,
        "equipment_module_ids": gleq.get_active_modules(),
        "tick_count": tick_count,
        "sector_layout": world.sector_grid.layout_id if world.sector_grid else None,
        "sector_grid_visibility": world.sector_grid.serialise() if world.sector_grid else None,
        "ship": _serialise_ship(world.ship),
        "entities": _serialise_entities(world),
        "modules": {
            "weapons": glw.serialise(),
            "medical": glmed.serialise(),
            "security": gls.serialise(),
            "flight_ops": glfo.serialise(),
            "damage_control": gldc.serialise(),
            "comms": glco.serialise(),
            "captain_log": glcap.serialise(),
            "training": gltr.serialise(),
            "ew": glew.serialise(),
            "tactical": gltac.serialise(),
            "mission": glm.serialise_mission(),
            "docking": gldo.serialise(),
            "engineering": gle.serialise(),
            "dynamic_missions": gldm.serialise(),
            "janitor": glj.serialise(),
            "equipment_modules": gleq.serialise(),
            "mining": glmn.serialise(),
            "flag_bridge": glfb.serialise(),
            "spinal_mount": glsm.serialise(),
            "carrier_ops": glcar.serialise(),
            "medical_ship": glms.serialise(),
            "loadout": gllo.serialise(),
            "game_state": game_state or {},
        },
    }

    SAVES_DIR.mkdir(parents=True, exist_ok=True)
    dest = SAVES_DIR / f"{save_id}.json"
    dest.write_text(json.dumps(save_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Game saved to %s", dest)
    return save_id


def list_saves() -> list[dict]:
    """Return summary list of available saves, newest first."""
    if not SAVES_DIR.exists():
        return []
    saves = []
    for path in SAVES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            saves.append({
                "save_id": data.get("save_id", path.stem),
                "saved_at": data.get("saved_at", ""),
                "mission_id": data.get("mission_id", ""),
                "mission_name": data.get("mission_name", data.get("mission_id", "")),
                "ship_class": data.get("ship_class", ""),
                "difficulty_preset": data.get("difficulty_preset", ""),
                "tick_count": data.get("tick_count", 0),
                "file": path.name,
            })
        except (json.JSONDecodeError, OSError):
            pass
    saves.sort(key=lambda s: s["saved_at"], reverse=True)
    return saves


def load_save(save_id: str) -> dict:
    """Load a save file by ID. Raises FileNotFoundError if not found."""
    path = SAVES_DIR / f"{save_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Save '{save_id}' not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def restore_game(save_id: str, world: World) -> dict:
    """Load a save and restore all game state into the running world.

    Restores ship, world entities, and all game-loop module state.
    Returns metadata: {mission_id, difficulty_preset, ship_class, tick_count}.
    """
    data = load_save(save_id)

    mission_id = data["mission_id"]
    difficulty_preset = data.get("difficulty_preset", "officer")
    ship_class = data.get("ship_class", "frigate")
    tick_count = int(data.get("tick_count", 0))

    # Restore ship state in-place (world.ship is a reference to the live ship).
    world.ship.interior = make_default_interior(ship_class)  # rebuild rooms before restoring state
    _deserialise_ship(data.get("ship", {}), world.ship)

    # Restore world entities (enemies, torpedoes, stations, asteroids, hazards).
    _deserialise_entities(data.get("entities", {}), world)

    # Restore each game-loop module.
    mods = data.get("modules", {})
    if mods.get("weapons"):
        glw.deserialise(mods["weapons"])
    if mods.get("medical"):
        glmed.deserialise(mods["medical"])
    if mods.get("security"):
        gls.deserialise(mods["security"])
    if mods.get("flight_ops"):
        glfo.deserialise(mods["flight_ops"])
    if mods.get("damage_control"):
        gldc.deserialise(mods["damage_control"])
    if mods.get("comms"):
        glco.deserialise(mods["comms"])
    if mods.get("captain_log"):
        glcap.deserialise(mods["captain_log"])
    if mods.get("training"):
        gltr.deserialise(mods["training"])
    if mods.get("ew"):
        glew.deserialise(mods["ew"])
    if mods.get("tactical"):
        gltac.deserialise(mods["tactical"])
    if mods.get("mission"):
        glm.deserialise_mission(mods["mission"], mission_id)
    if mods.get("docking"):
        gldo.deserialise(mods["docking"])
    if mods.get("engineering"):
        gle.deserialise(mods["engineering"], world.ship)
    if mods.get("dynamic_missions"):
        gldm.deserialise(mods["dynamic_missions"])
    if mods.get("janitor"):
        glj.deserialise(mods["janitor"])
    if mods.get("equipment_modules"):
        gleq.deserialise(mods["equipment_modules"])
    if mods.get("mining"):
        glmn.deserialise(mods["mining"])
    if mods.get("flag_bridge"):
        glfb.deserialise(mods["flag_bridge"])
    if mods.get("spinal_mount"):
        glsm.deserialise(mods["spinal_mount"])
    if mods.get("carrier_ops"):
        glcar.deserialise(mods["carrier_ops"])
    if mods.get("medical_ship"):
        glms.deserialise(mods["medical_ship"])
    if "loadout" in mods:
        gllo.deserialise(mods["loadout"])

    # Restore sector grid visibility (v0.05b).
    sector_layout = data.get("sector_layout")
    if sector_layout:
        try:
            from server.models.sector import load_sector_grid
            grid = load_sector_grid(sector_layout)
            grid.apply_transponder_reveals()
            vis_data = data.get("sector_grid_visibility")
            if vis_data:
                grid.deserialise_visibility(vis_data)
            world.sector_grid = grid
        except FileNotFoundError:
            logger.warning("Sector layout %r not found during restore", sector_layout)
            world.sector_grid = None
    else:
        world.sector_grid = None

    logger.info(
        "Game restored from save '%s' (mission=%s, tick=%d)",
        save_id, mission_id, tick_count,
    )
    return {
        "mission_id": mission_id,
        "difficulty_preset": difficulty_preset,
        "ship_class": ship_class,
        "tick_count": tick_count,
        "game_state": mods.get("game_state", {}),
    }
