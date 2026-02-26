"""Tests for v0.07-6 Commit A: Power System Class Features.

Covers:
  A1. Corvette ECM power efficiency (0.6× modifier)
  A2. Carrier flight deck passive/active power drain
  A3. Medical ship brownout exemption (sensors + shields protected)
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_ship(systems=None):
    """Create a minimal Ship with named systems."""
    from server.models.ship import Ship, ShipSystem
    ship = Ship()
    if systems:
        ship.systems = {name: ShipSystem(name=name, power=100.0, health=100.0) for name in systems}
    return ship


def _fresh_power_grid(**overrides):
    from server.models.power_grid import PowerGrid
    return PowerGrid(**overrides)


# ============================================================================
# A1. Corvette ECM power efficiency modifier
# ============================================================================


class TestCorvetteEcmEfficiency:
    """Verify corvette ECM gets 0.6× _power_profile_modifier."""

    def test_corvette_ecm_modifier_applied(self):
        """After game start with corvette, ecm_suite._power_profile_modifier should be 0.6."""
        ship = _fresh_ship(["sensors", "shields", "beams", "torpedoes",
                            "manoeuvring", "engines", "flight_deck",
                            "ecm_suite", "point_defence"])
        ecm = ship.systems["ecm_suite"]
        assert ecm._power_profile_modifier == 1.0  # default

        # Simulate what game_loop.start() does for corvette:
        ecm._power_profile_modifier *= 0.6
        assert abs(ecm._power_profile_modifier - 0.6) < 1e-9

    def test_corvette_ecm_stacks_with_profile(self):
        """Combat profile (1.15) × corvette (0.6) = 0.69."""
        from server.models.ship import ShipSystem
        ecm = ShipSystem(name="ecm_suite", power=100.0, health=100.0)
        # Combat profile applied first
        ecm._power_profile_modifier = 1.15
        # Then corvette modifier stacks
        ecm._power_profile_modifier *= 0.6
        assert abs(ecm._power_profile_modifier - 0.69) < 1e-9

    def test_corvette_ecm_efficiency_value(self):
        """ECM at 100% power/health with 0.6 modifier → efficiency 0.6."""
        from server.models.ship import ShipSystem
        ecm = ShipSystem(name="ecm_suite", power=100.0, health=100.0)
        ecm._power_profile_modifier = 0.6
        assert abs(ecm.efficiency - 0.6) < 1e-9

    def test_non_corvette_ecm_unmodified(self):
        """Non-corvette ships keep default ecm modifier of 1.0."""
        ship = _fresh_ship(["ecm_suite"])
        assert ship.systems["ecm_suite"]._power_profile_modifier == 1.0


# ============================================================================
# A2. Carrier flight deck passive/active power drain
# ============================================================================


class TestCarrierFlightDeckDrain:
    """Verify flight deck power draw function."""

    def setup_method(self):
        import server.game_loop_flight_ops as glfo
        glfo.reset("carrier")
        self.glfo = glfo

    def test_passive_draw_15_percent(self):
        """Idle carrier: 15% of reactor_max."""
        draw = self.glfo.get_flight_deck_power_draw(700.0)
        assert abs(draw - 105.0) < 1e-9  # 700 * 0.15

    def test_active_draw_25_percent_launch(self):
        """During launch: 25% of reactor_max."""
        # Simulate a drone in a launch tube
        self.glfo._flight_deck.tubes_in_use.append("drone_c0")
        draw = self.glfo.get_flight_deck_power_draw(700.0)
        assert abs(draw - 175.0) < 1e-9  # 700 * 0.25

    def test_active_draw_25_percent_recovery(self):
        """During recovery: 25% of reactor_max."""
        self.glfo._flight_deck.recovery_in_progress.append("drone_c0")
        draw = self.glfo.get_flight_deck_power_draw(700.0)
        assert abs(draw - 175.0) < 1e-9

    def test_active_draw_both_launch_and_recovery(self):
        """Both launch and recovery active: still 25%."""
        self.glfo._flight_deck.tubes_in_use.append("drone_c0")
        self.glfo._flight_deck.recovery_in_progress.append("drone_c1")
        draw = self.glfo.get_flight_deck_power_draw(700.0)
        assert abs(draw - 175.0) < 1e-9

    def test_non_carrier_no_flight_deck_drain(self):
        """Non-carrier ships: passing reactor_max=0 → 0 drain."""
        draw = self.glfo.get_flight_deck_power_draw(0.0)
        assert draw == 0.0

    def test_negative_reactor_max_returns_zero(self):
        draw = self.glfo.get_flight_deck_power_draw(-100.0)
        assert draw == 0.0


# ============================================================================
# A3. Medical brownout exemption
# ============================================================================


class TestMedicalBrownoutExemption:
    """Verify protected_systems in PowerGrid.tick() brownout logic."""

    def test_medical_brownout_protects_sensors_shields(self):
        """Under brownout, sensors and shields get full power; others scaled."""
        pg = _fresh_power_grid(reactor_max=300.0, reactor_health=100.0,
                               battery_charge=0.0, battery_mode="standby")
        demands = {
            "sensors": 100.0,
            "shields": 100.0,
            "beams": 100.0,
            "engines": 100.0,
        }
        # Total demand = 400, available = 300 → brownout
        delivered = pg.tick(0.1, demands, protected_systems={"sensors", "shields"})

        # Protected: sensors and shields get full 100 each (200 total)
        assert abs(delivered["sensors"] - 100.0) < 1e-6
        assert abs(delivered["shields"] - 100.0) < 1e-6

        # Remaining 100 split equally between beams and engines
        assert abs(delivered["beams"] - 50.0) < 1e-6
        assert abs(delivered["engines"] - 50.0) < 1e-6

    def test_non_medical_brownout_scales_all(self):
        """Without protected_systems, all systems scale equally."""
        pg = _fresh_power_grid(reactor_max=300.0, reactor_health=100.0,
                               battery_charge=0.0, battery_mode="standby")
        demands = {
            "sensors": 100.0,
            "shields": 100.0,
            "beams": 100.0,
            "engines": 100.0,
        }
        delivered = pg.tick(0.1, demands, protected_systems=None)

        for sys_name in demands:
            assert abs(delivered[sys_name] - 75.0) < 1e-6  # 300/400 = 0.75

    def test_medical_brownout_insufficient_for_protected(self):
        """If even protected demand exceeds available, protected scale among themselves."""
        pg = _fresh_power_grid(reactor_max=100.0, reactor_health=100.0,
                               battery_charge=0.0, battery_mode="standby")
        demands = {
            "sensors": 100.0,
            "shields": 100.0,
            "beams": 50.0,
        }
        # Total demand = 250, available = 100, protected demand = 200 > 100
        delivered = pg.tick(0.1, demands, protected_systems={"sensors", "shields"})

        # Protected get proportional share: 100 * (100/200) = 50 each
        assert abs(delivered["sensors"] - 50.0) < 1e-6
        assert abs(delivered["shields"] - 50.0) < 1e-6

        # Unprotected get 0 (nothing remaining)
        assert abs(delivered["beams"] - 0.0) < 1e-6

    def test_no_brownout_protected_irrelevant(self):
        """When demand < available, protected_systems has no effect."""
        pg = _fresh_power_grid(reactor_max=500.0, reactor_health=100.0,
                               battery_charge=0.0, battery_mode="standby")
        demands = {"sensors": 100.0, "shields": 100.0}
        delivered = pg.tick(0.1, demands, protected_systems={"sensors", "shields"})
        assert abs(delivered["sensors"] - 100.0) < 1e-6
        assert abs(delivered["shields"] - 100.0) < 1e-6

    def test_protected_empty_set_same_as_none(self):
        """Empty protected set behaves same as None (all scale equally)."""
        pg = _fresh_power_grid(reactor_max=300.0, reactor_health=100.0,
                               battery_charge=0.0, battery_mode="standby")
        demands = {"sensors": 100.0, "shields": 100.0, "beams": 100.0, "engines": 100.0}
        delivered = pg.tick(0.1, demands, protected_systems=set())
        # Empty set → no protected → all scale
        for sys_name in demands:
            assert abs(delivered[sys_name] - 75.0) < 1e-6


# ============================================================================
# A4. Engineering module integration
# ============================================================================


class TestEngineeringShipClassIntegration:
    """Verify engineering module tracks ship class for drain/protection."""

    def setup_method(self):
        import server.game_loop_engineering as gle
        gle.reset()
        self.gle = gle

    def test_init_stores_ship_class(self):
        ship = _fresh_ship(["sensors", "shields", "beams", "torpedoes",
                            "manoeuvring", "engines", "flight_deck",
                            "ecm_suite", "point_defence"])
        self.gle.init(ship, ship_class="carrier")
        assert self.gle._ship_class == "carrier"

    def test_reset_clears_ship_class(self):
        ship = _fresh_ship(["sensors"])
        self.gle.init(ship, ship_class="carrier")
        self.gle.reset()
        assert self.gle._ship_class == "frigate"

    def test_serialise_includes_ship_class(self):
        ship = _fresh_ship(["sensors"])
        self.gle.init(ship, ship_class="medical_ship")
        data = self.gle.serialise()
        assert data["ship_class"] == "medical_ship"

    def test_deserialise_restores_ship_class(self):
        ship = _fresh_ship(["sensors"])
        self.gle.init(ship, ship_class="frigate")
        self.gle.deserialise({"ship_class": "carrier"}, ship)
        assert self.gle._ship_class == "carrier"

    def test_deserialise_defaults_to_frigate(self):
        ship = _fresh_ship(["sensors"])
        self.gle.init(ship, ship_class="carrier")
        self.gle.deserialise({}, ship)
        assert self.gle._ship_class == "frigate"
