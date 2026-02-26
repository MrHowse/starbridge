"""Tests for v0.07 §3: Pre-Mission Loadout Configuration."""
from __future__ import annotations

import pytest

import server.loadout as gllo
from server.loadout import (
    CREW_BIAS_DEPARTMENTS,
    CREW_PRESETS,
    DRONE_PRESETS,
    POWER_PROFILES,
    TORPEDO_COSTS,
    TORPEDO_PRESETS,
    VALID_POWER_PROFILES,
    CrewBias,
    DroneLoadout,
    LoadoutConfig,
    TorpedoLoadout,
    apply_drone_loadout,
    apply_power_profile,
    apply_torpedo_loadout,
    compute_crew_bias_deck_adjustments,
    generate_crew_preset,
    generate_drone_preset,
    generate_torpedo_preset,
    get_default_loadout,
    get_loadout_defaults,
    validate_crew_bias,
    validate_drone_loadout,
    validate_loadout,
    validate_power_profile,
    validate_torpedo_loadout,
)
from server.models.drones import DRONE_COMPLEMENT, HANGAR_SLOTS, create_ship_drones
from server.models.ship import ShipSystem
from server.models.ship_class import SHIP_CLASS_ORDER, load_ship_class


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset():
    gllo.reset()


# ===========================================================================
# Torpedo Loadout Validation
# ===========================================================================


class TestTorpedoValidation:

    def test_valid_within_capacity(self):
        """A loadout that fits within magazine capacity passes."""
        _reset()
        sc = load_ship_class("frigate")
        cap = sc.torpedo_ammo  # 12
        lo = TorpedoLoadout(standard=cap)  # 12 × 1pt = 12
        ok, err = validate_torpedo_loadout(lo, "frigate")
        assert ok, err

    def test_over_capacity_rejected(self):
        """A loadout exceeding magazine capacity fails."""
        _reset()
        lo = TorpedoLoadout(standard=100)
        ok, err = validate_torpedo_loadout(lo, "frigate")
        assert not ok
        assert "capacity" in err.lower()

    def test_negative_count_rejected(self):
        """Negative torpedo counts fail validation."""
        _reset()
        lo = TorpedoLoadout(standard=-1)
        ok, err = validate_torpedo_loadout(lo, "frigate")
        assert not ok
        assert "negative" in err.lower()

    def test_empty_loadout_valid(self):
        """All-zero loadout is valid (uses 0 points)."""
        _reset()
        lo = TorpedoLoadout()
        ok, err = validate_torpedo_loadout(lo, "frigate")
        assert ok

    def test_per_ship_class_capacity(self):
        """Different ship classes have different magazine capacities."""
        _reset()
        scout = load_ship_class("scout")
        battleship = load_ship_class("battleship")
        assert scout.torpedo_ammo != battleship.torpedo_ammo

    def test_exactly_at_capacity_passes(self):
        """Using exactly the full capacity passes."""
        _reset()
        sc = load_ship_class("frigate")
        cap = sc.torpedo_ammo
        # nuclear=5pt each, so cap//5 nukes, remainder in standard(1pt each)
        n_nukes = cap // 5
        remainder = cap - n_nukes * 5
        lo = TorpedoLoadout(nuclear=n_nukes, standard=remainder)
        assert lo.total_points() == cap
        ok, _ = validate_torpedo_loadout(lo, "frigate")
        assert ok

    def test_unknown_ship_class_rejected(self):
        """Unknown ship class fails validation."""
        _reset()
        lo = TorpedoLoadout(standard=1)
        ok, err = validate_torpedo_loadout(lo, "nonexistent_ship")
        assert not ok
        assert "unknown" in err.lower()

    def test_mixed_types_within_capacity(self):
        """A mix of torpedo types within capacity passes."""
        _reset()
        # frigate has 12 points capacity
        lo = TorpedoLoadout(standard=2, homing=2, piercing=1)  # 2+4+2 = 8
        ok, err = validate_torpedo_loadout(lo, "frigate")
        assert ok, err


# ===========================================================================
# Torpedo Presets
# ===========================================================================


class TestTorpedoPresets:

    def test_balanced_fits_within_capacity(self):
        """Balanced preset fits within magazine capacity."""
        _reset()
        for sc_id in SHIP_CLASS_ORDER:
            lo = generate_torpedo_preset("balanced", sc_id)
            sc = load_ship_class(sc_id)
            assert lo.total_points() <= sc.torpedo_ammo, f"{sc_id}: {lo.total_points()} > {sc.torpedo_ammo}"

    def test_aggressive_fits_within_capacity(self):
        """Aggressive preset fits within magazine capacity."""
        _reset()
        for sc_id in SHIP_CLASS_ORDER:
            lo = generate_torpedo_preset("aggressive", sc_id)
            sc = load_ship_class(sc_id)
            assert lo.total_points() <= sc.torpedo_ammo

    def test_all_presets_produce_valid_loadout(self):
        """Every preset generates a valid loadout for every ship class."""
        _reset()
        for preset_name in TORPEDO_PRESETS:
            for sc_id in SHIP_CLASS_ORDER:
                lo = generate_torpedo_preset(preset_name, sc_id)
                ok, err = validate_torpedo_loadout(lo, sc_id)
                assert ok, f"Preset {preset_name} for {sc_id}: {err}"

    def test_default_loadout_is_balanced(self):
        """Default loadout uses balanced torpedo preset."""
        _reset()
        default = get_default_loadout("frigate")
        balanced = generate_torpedo_preset("balanced", "frigate")
        assert default.torpedo_loadout == balanced

    def test_difficulty_multiplier_applied(self):
        """apply_torpedo_loadout applies difficulty multiplier."""
        _reset()
        lo = TorpedoLoadout(standard=10)
        result = apply_torpedo_loadout(lo, difficulty_multiplier=2.0)
        assert result["standard"] == 20


# ===========================================================================
# Power Profile Validation
# ===========================================================================


class TestPowerProfileValidation:

    def test_all_five_profiles_accepted(self):
        """All 5 power profiles pass validation."""
        for name in VALID_POWER_PROFILES:
            ok, err = validate_power_profile(name)
            assert ok, f"{name}: {err}"

    def test_unknown_profile_rejected(self):
        """Unknown profile fails validation."""
        ok, err = validate_power_profile("turbo_max")
        assert not ok
        assert "unknown" in err.lower()

    def test_combat_profile_exists(self):
        """Combat profile has weapons and shields boost."""
        defn = POWER_PROFILES["combat"]
        assert defn.get("weapons") == 1.15
        assert defn.get("shields") == 1.15

    def test_exploration_profile_exists(self):
        """Exploration profile has sensors and engines boost."""
        defn = POWER_PROFILES["exploration"]
        assert defn.get("sensors") == 1.15
        assert defn.get("engines") == 1.15

    def test_emergency_overclocked_grid_mods(self):
        """Emergency and overclocked profiles have grid modifiers."""
        assert "emergency_reserve_mult" in POWER_PROFILES["emergency"]
        assert "reactor_output_mult" in POWER_PROFILES["overclocked"]
        assert "battery_capacity_mult" in POWER_PROFILES["overclocked"]


# ===========================================================================
# Power Profile Application
# ===========================================================================


class TestPowerProfileApplication:

    def _make_ship_mock(self):
        """Create a minimal mock ship with systems."""
        class MockShip:
            def __init__(self):
                self.systems = {
                    "beams": ShipSystem(name="beams"),
                    "torpedoes": ShipSystem(name="torpedoes"),
                    "shields": ShipSystem(name="shields"),
                    "sensors": ShipSystem(name="sensors"),
                    "engines": ShipSystem(name="engines"),
                    "manoeuvring": ShipSystem(name="manoeuvring"),
                    "point_defence": ShipSystem(name="point_defence"),
                }
        return MockShip()

    def _make_grid_mock(self):
        class MockGrid:
            def __init__(self):
                self.reactor_max = 700.0
                self.reactor_health = 100.0
                self.battery_capacity = 500.0
                self.battery_charge = 250.0
                self.emergency_reserve = 100.0
        return MockGrid()

    def test_balanced_no_changes(self):
        """Balanced profile makes no modifications."""
        ship = self._make_ship_mock()
        grid = self._make_grid_mock()
        apply_power_profile("balanced", ship, grid)
        for sys in ship.systems.values():
            assert sys._power_profile_modifier == 1.0
        assert grid.reactor_max == 700.0

    def test_combat_weapons_shields_boosted(self):
        """Combat profile boosts weapons/shields, reduces sensors/engines."""
        ship = self._make_ship_mock()
        apply_power_profile("combat", ship)
        assert ship.systems["beams"]._power_profile_modifier == 1.15
        assert ship.systems["torpedoes"]._power_profile_modifier == 1.15
        assert ship.systems["shields"]._power_profile_modifier == 1.15
        assert ship.systems["sensors"]._power_profile_modifier == 0.85
        assert ship.systems["engines"]._power_profile_modifier == 0.85

    def test_exploration_sensors_engines_boosted(self):
        """Exploration profile boosts sensors/engines, reduces weapons/shields."""
        ship = self._make_ship_mock()
        apply_power_profile("exploration", ship)
        assert ship.systems["sensors"]._power_profile_modifier == 1.15
        assert ship.systems["engines"]._power_profile_modifier == 1.15
        assert ship.systems["beams"]._power_profile_modifier == 0.85
        assert ship.systems["shields"]._power_profile_modifier == 0.85

    def test_emergency_reserve_and_reactor(self):
        """Emergency profile: +50% emergency reserve, -10% reactor."""
        ship = self._make_ship_mock()
        grid = self._make_grid_mock()
        apply_power_profile("emergency", ship, grid)
        assert grid.emergency_reserve == 150.0  # 100 * 1.5
        assert grid.reactor_max == 630.0  # 700 * 0.9

    def test_overclocked_reactor_battery_coolant(self):
        """Overclocked: +10% reactor, -25% battery, coolant 80%."""
        ship = self._make_ship_mock()
        grid = self._make_grid_mock()
        apply_power_profile("overclocked", ship, grid)
        assert grid.reactor_max == 770.0  # 700 * 1.1
        assert grid.battery_capacity == 375.0  # 500 * 0.75
        assert grid.battery_charge <= grid.battery_capacity
        assert grid.reactor_health == 80.0

    def test_modifier_in_efficiency(self):
        """Power profile modifier is included in ShipSystem.efficiency."""
        sys = ShipSystem(name="beams", power=100.0, health=100.0)
        base = sys.efficiency
        sys._power_profile_modifier = 1.15
        assert sys.efficiency == pytest.approx(base * 1.15, abs=0.001)

    def test_modifier_stacks_with_crew_and_maintenance(self):
        """Profile modifier stacks with crew factor and maintenance buff."""
        sys = ShipSystem(name="beams", power=100.0, health=100.0)
        sys._crew_factor = 0.8
        sys._power_profile_modifier = 1.15
        sys._maintenance_buff = 0.05
        expected = (100/100) * (100/100) * 0.8 * 1.15 + 0.05
        assert sys.efficiency == pytest.approx(expected, abs=0.001)


# ===========================================================================
# Crew Bias Validation
# ===========================================================================


class TestCrewBiasValidation:

    def test_valid_zero_sum(self):
        """Zero-sum bias passes."""
        _reset()
        bias = CrewBias(engineering=2, medical=-2)
        ok, err = validate_crew_bias(bias)
        assert ok, err

    def test_non_zero_sum_rejected(self):
        """Non-zero-sum bias fails."""
        _reset()
        bias = CrewBias(engineering=2)
        ok, err = validate_crew_bias(bias)
        assert not ok
        assert "sum" in err.lower()

    def test_over_limit_rejected(self):
        """Values outside ±2 fail."""
        _reset()
        bias = CrewBias(engineering=3, medical=-3)
        ok, err = validate_crew_bias(bias)
        assert not ok

    def test_empty_bias_valid(self):
        """All-zero bias is valid."""
        _reset()
        bias = CrewBias()
        ok, _ = validate_crew_bias(bias)
        assert ok

    def test_all_departments_adjustable(self):
        """All 6 departments can be adjusted."""
        assert len(CREW_BIAS_DEPARTMENTS) == 6
        for dept in CREW_BIAS_DEPARTMENTS:
            assert hasattr(CrewBias(), dept)

    def test_crew_count_preserved(self):
        """Crew bias adjustments preserve total crew count."""
        bias = CrewBias(engineering=2, security=1, weapons=-1, medical=-2)
        adjustments = compute_crew_bias_deck_adjustments(bias, 7, num_decks=5)
        assert sum(adjustments.values()) == 7


# ===========================================================================
# Crew Bias Application
# ===========================================================================


class TestCrewBiasApplication:

    def test_bias_adjusts_deck_sizes(self):
        """Non-zero bias changes deck crew counts."""
        bias = CrewBias(engineering=2, medical=-2)
        base = compute_crew_bias_deck_adjustments(CrewBias(), 10, num_decks=5)
        adjusted = compute_crew_bias_deck_adjustments(bias, 10, num_decks=5)
        # Deck 5 (engineering) should increase, Deck 4 (medical) should decrease.
        assert adjusted[5] > base[5]

    def test_zero_bias_default_distribution(self):
        """Zero bias produces the same as default distribution."""
        bias = CrewBias()
        adj = compute_crew_bias_deck_adjustments(bias, 10, num_decks=5)
        assert sum(adj.values()) == 10

    def test_combat_preset(self):
        """Combat preset has weapons+, security+, science-, medical-."""
        preset = generate_crew_preset("combat")
        d = preset.to_dict()
        assert d["weapons"] == 2
        assert d["security"] == 1
        assert d["science"] == -1
        assert d["medical"] == -2
        assert sum(d.values()) == 0

    def test_generated_roster_reflects_bias(self):
        """IndividualCrewRoster.generate() uses deck_counts when provided."""
        from server.models.crew_roster import IndividualCrewRoster
        import random as _rng

        bias = CrewBias(engineering=2, medical=-2)
        deck_adj = compute_crew_bias_deck_adjustments(bias, 7, num_decks=5)

        rng = _rng.Random(42)
        roster = IndividualCrewRoster.generate(7, ship_class="frigate", rng=rng, deck_counts=deck_adj)
        # Count crew per deck.
        deck_counts = {}
        for m in roster.members.values():
            deck_counts[m.deck] = deck_counts.get(m.deck, 0) + 1
        # Total should match.
        assert sum(deck_counts.values()) == 7
        # Deck 5 should have the engineering bias boost.
        assert deck_counts.get(5, 0) == deck_adj[5]


# ===========================================================================
# Drone Loadout Validation
# ===========================================================================


class TestDroneLoadoutValidation:

    def test_valid_within_hangar(self):
        """Loadout within hangar slots passes."""
        _reset()
        cap = HANGAR_SLOTS["frigate"]
        lo = DroneLoadout(scout=cap)
        ok, err = validate_drone_loadout(lo, "frigate")
        assert ok, err

    def test_over_capacity_rejected(self):
        """Exceeding hangar slots fails."""
        _reset()
        lo = DroneLoadout(scout=100)
        ok, err = validate_drone_loadout(lo, "frigate")
        assert not ok

    def test_negative_rejected(self):
        """Negative drone count fails."""
        _reset()
        lo = DroneLoadout(scout=-1)
        ok, err = validate_drone_loadout(lo, "frigate")
        assert not ok

    def test_empty_valid(self):
        """All-zero drone loadout is valid."""
        _reset()
        lo = DroneLoadout()
        ok, _ = validate_drone_loadout(lo, "frigate")
        assert ok

    def test_all_ship_classes_have_hangar(self):
        """All ship classes have hangar slot entries."""
        for sc_id in SHIP_CLASS_ORDER:
            assert sc_id in HANGAR_SLOTS


# ===========================================================================
# Drone Presets
# ===========================================================================


class TestDronePresets:

    def test_balanced_fills_all_slots(self):
        """Balanced drone preset uses all hangar slots."""
        _reset()
        lo = generate_drone_preset("balanced", "frigate")
        cap = HANGAR_SLOTS["frigate"]
        assert lo.total() == cap

    def test_recon_emphasises_scouts(self):
        """Recon preset has majority scout drones."""
        _reset()
        lo = generate_drone_preset("recon", "frigate")
        d = lo.to_dict()
        assert d["scout"] >= d.get("combat", 0)

    def test_all_presets_valid_for_each_class(self):
        """Every drone preset is valid for every ship class."""
        _reset()
        for preset in DRONE_PRESETS:
            for sc_id in SHIP_CLASS_ORDER:
                lo = generate_drone_preset(preset, sc_id)
                ok, err = validate_drone_loadout(lo, sc_id)
                assert ok, f"Preset {preset} for {sc_id}: {err}"

    def test_preset_scaled_to_hangar(self):
        """Presets scale to each ship's hangar capacity."""
        _reset()
        for sc_id in SHIP_CLASS_ORDER:
            lo = generate_drone_preset("balanced", sc_id)
            cap = HANGAR_SLOTS[sc_id]
            assert lo.total() == cap, f"{sc_id}: {lo.total()} != {cap}"


# ===========================================================================
# Full LoadoutConfig Validation
# ===========================================================================


class TestLoadoutConfigValidation:

    def test_all_none_defaults_valid(self):
        """Config with all None fields is valid."""
        _reset()
        config = LoadoutConfig()
        ok, err = validate_loadout(config, "frigate")
        assert ok, err

    def test_full_config_valid(self):
        """A fully specified config validates."""
        _reset()
        config = LoadoutConfig(
            torpedo_loadout=TorpedoLoadout(standard=10),
            power_profile="combat",
            crew_bias=CrewBias(engineering=1, medical=-1),
            drone_loadout=DroneLoadout(scout=2, combat=2),
        )
        ok, err = validate_loadout(config, "frigate")
        assert ok, err

    def test_partial_config_valid(self):
        """Config with only torpedo loadout validates."""
        _reset()
        config = LoadoutConfig(torpedo_loadout=TorpedoLoadout(standard=5))
        ok, err = validate_loadout(config, "frigate")
        assert ok, err

    def test_invalid_sub_config_fails(self):
        """Invalid torpedo loadout fails the whole config."""
        _reset()
        config = LoadoutConfig(
            torpedo_loadout=TorpedoLoadout(standard=1000),
            power_profile="balanced",
        )
        ok, err = validate_loadout(config, "frigate")
        assert not ok


# ===========================================================================
# Serialise / Deserialise
# ===========================================================================


class TestSerialisation:

    def test_round_trip(self):
        """Loadout survives serialise → deserialise."""
        _reset()
        config = LoadoutConfig(
            torpedo_loadout=TorpedoLoadout(standard=5, homing=2),
            power_profile="combat",
            crew_bias=CrewBias(engineering=1, medical=-1),
            drone_loadout=DroneLoadout(scout=2, combat=1),
        )
        gllo.set_loadout(config)
        data = gllo.serialise()
        gllo.reset()
        gllo.deserialise(data)
        restored = gllo.get_loadout()
        assert restored is not None
        assert restored.power_profile == "combat"
        assert restored.torpedo_loadout.standard == 5
        assert restored.crew_bias.engineering == 1

    def test_none_serialises_empty(self):
        """None loadout serialises to empty dict."""
        _reset()
        data = gllo.serialise()
        assert data == {}

    def test_deserialise_empty_gives_none(self):
        """Deserialising empty dict gives None loadout."""
        _reset()
        gllo.deserialise({})
        assert gllo.get_loadout() is None

    def test_power_profile_preserved(self):
        """Power profile name survives round-trip."""
        _reset()
        config = LoadoutConfig(power_profile="overclocked")
        gllo.set_loadout(config)
        data = gllo.serialise()
        gllo.reset()
        gllo.deserialise(data)
        assert gllo.get_power_profile() == "overclocked"


# ===========================================================================
# Integration with game_loop (via mocked subsystems)
# ===========================================================================


class TestIntegration:

    def test_lobby_payload_has_loadout_field(self):
        """LobbyStartGamePayload accepts loadout dict."""
        from server.models.messages.lobby import LobbyStartGamePayload
        p = LobbyStartGamePayload(mission_id="sandbox", loadout={"power_profile": "combat"})
        assert p.loadout == {"power_profile": "combat"}

    def test_torpedo_loadout_overrides_default(self):
        """apply_torpedo_loadout returns custom counts."""
        lo = TorpedoLoadout(standard=3, homing=2)
        result = apply_torpedo_loadout(lo)
        assert result["standard"] == 3
        assert result["homing"] == 2
        assert result["nuclear"] == 0

    def test_drone_loadout_override(self):
        """apply_drone_loadout returns override complement."""
        lo = DroneLoadout(scout=3, combat=1)
        result = apply_drone_loadout(lo)
        assert result["scout"] == 3
        assert result["combat"] == 1
        assert "rescue" not in result

    def test_create_ship_drones_with_override(self):
        """create_ship_drones() uses complement_override when provided."""
        override = {"scout": 2, "rescue": 1}
        drones = create_ship_drones("frigate", complement_override=override)
        types = [d.drone_type for d in drones]
        assert types.count("scout") == 2
        assert types.count("rescue") == 1
        assert types.count("combat") == 0  # not in override

    def test_build_state_includes_profile(self):
        """build_state() includes power_profile."""
        _reset()
        config = LoadoutConfig(power_profile="exploration")
        gllo.set_loadout(config)
        state = gllo.build_state()
        assert state["power_profile"] == "exploration"


# ===========================================================================
# REST Endpoints
# ===========================================================================


class TestRESTEndpoints:

    def test_get_defaults_structure(self):
        """get_loadout_defaults returns expected keys."""
        defaults = get_loadout_defaults("frigate")
        assert "torpedo_capacity" in defaults
        assert "torpedo_costs" in defaults
        assert "torpedo_presets" in defaults
        assert "power_profiles" in defaults
        assert "crew_bias_departments" in defaults
        assert "crew_presets" in defaults
        assert "hangar_slots" in defaults
        assert "drone_presets" in defaults
        assert "available_drone_types" in defaults
        assert "default_loadout" in defaults

    def test_get_defaults_torpedo_capacity(self):
        """Torpedo capacity matches ship class."""
        sc = load_ship_class("frigate")
        defaults = get_loadout_defaults("frigate")
        assert defaults["torpedo_capacity"] == sc.torpedo_ammo

    def test_endpoint_validate_via_fastapi(self):
        """POST /api/loadout/validate returns expected response."""
        from starlette.testclient import TestClient
        from server.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/loadout/validate", json={
            "ship_class": "frigate",
            "loadout": {"power_profile": "balanced"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True

    def test_endpoint_defaults_via_fastapi(self):
        """GET /api/loadout/defaults/frigate returns expected structure."""
        from starlette.testclient import TestClient
        from server.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/loadout/defaults/frigate")
        assert resp.status_code == 200
        data = resp.json()
        assert "torpedo_capacity" in data


# ===========================================================================
# Debrief
# ===========================================================================


class TestDebrief:

    def test_debrief_includes_loadout(self):
        """compute_debrief includes loadout state."""
        _reset()
        config = LoadoutConfig(power_profile="combat")
        gllo.set_loadout(config)
        from server.game_debrief import compute_debrief
        result = compute_debrief([])
        assert "loadout" in result
        assert result["loadout"]["power_profile"] == "combat"

    def test_debrief_default_loadout(self):
        """Debrief with no loadout shows balanced default."""
        _reset()
        from server.game_debrief import compute_debrief
        result = compute_debrief([])
        assert result["loadout"]["power_profile"] == "balanced"
